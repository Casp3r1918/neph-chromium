"""The "extensions_ui" patch of apply.py: Chrome hands its question before an
extension install, and its note after it, to the host (24.10.2026, Opus 5.5).

The publisher, installing an extension from the Chrome Web Store: "dann öffnet
sich ein extra Tab einfach so" and "passe den Erweiterungen hinzufügen Pop-up
besser zu nephs vibe an mach es cleaner und gebe ihn nach rechts nicht nach
links". Both come from Chrome's own UI, which has no place in Neph's window:

1. The question ("„…“ hinzufügen?") is a browser-modal dialog of Chrome's
   (ShowExtensionInstallDialogImpl), which in CEF's Chrome style lands at the
   top left of the content area. With the host's hooks registered, the
   question goes to the host instead (prompt), which asks it in its own
   flyout, right-aligned under its extensions button, and answers through the
   exported neph_extensions_ui_answer; Chrome's callback waits for that. Only
   the install, re-enable and permissions questions go to the host, and none
   that needs a parent's permission; the rest stays Chrome's dialog.
2. The note after an install (ExtensionInstallUIDesktop::OnInstallSuccess)
   looks for one of Chrome's tabbed windows, opens one with an empty tab when
   there is none - Neph's tabs are not such windows - and anchors its bubble
   there. With the hooks the host is told instead (installed) and announces
   the extension in its toolbar; Chrome opens nothing.

Without hooks (no host, or an older host) everything stays as it was. The ABI
(struct NephExtensionsUiHooks, the answers) is the one in
src/native/extensions_ui_hooks.h; change both together. Only .cc files change.
"""


class AnchorMissing(Exception):
    pass


def replace_once(text, old, new, what):
    if text.count(old) != 1:
        raise AnchorMissing('%s: %s (found %d times)' % (what, old.strip().splitlines()[0], text.count(old)))
    return text.replace(old, new, 1)


MARK = 'Neph (24.10.2026, Opus 5.5): the host asks the install question itself'

DIALOG = 'chrome/browser/ui/views/extensions/extension_install_dialog_view.cc'
DESKTOP = 'chrome/browser/ui/extensions/extension_install_ui_desktop.cc'
FILES = (DIALOG, DESKTOP)

HOOKS = r'''
// Neph (24.10.2026, Opus 5.5): the host asks the install question itself, in
// the form of its own menus under its extensions button, and announces an
// installed extension itself; Chrome's dialog lands at the top left of the
// page and its note opens a window of Chrome's own
// (scripts/chromium-patches/extensions_ui_patch.py; src/native/extensions_ui_hooks.h
// holds the same ABI on the host side). Without hooks everything stays Chrome's.
#include <atomic>
#include <cstdint>
#include <map>
#include <optional>
#include <vector>

#include "base/base64.h"
#include "base/json/json_writer.h"
#include "base/location.h"
#include "base/no_destructor.h"
#include "base/task/single_thread_task_runner.h"
#include "base/values.h"
#include "build/build_config.h"
#include "content/public/browser/browser_task_traits.h"
#include "ui/gfx/codec/png_codec.h"
#include "ui/gfx/image/image.h"

#if BUILDFLAG(IS_WIN)
#define NEPH_EXTENSIONS_UI_EXPORT __declspec(dllexport)
#else
#define NEPH_EXTENSIONS_UI_EXPORT __attribute__((visibility("default")))
#endif

extern "C" {
struct NephExtensionsUiHooks {
  uint32_t size;
  uint32_t version;  // 1
  // The question before an install: |json| (UTF-8) carries the texts Chrome's
  // dialog would show. 1: the host asks it and answers later through
  // neph_extensions_ui_answer(|id|, ...); anything else: Chrome's dialog.
  int (*prompt)(int32_t id, const char* json);
  // The question |id| is void; the host closes its dialog without answering.
  void (*withdraw)(int32_t id);
  // Chrome installed an extension the user said yes to: |json| = {id, name}.
  // 1: the host announces it; anything else: Chrome's note.
  int (*installed)(const char* json);
};
NEPH_EXTENSIONS_UI_EXPORT void neph_extensions_ui_set_hooks(
    const NephExtensionsUiHooks* hooks);
NEPH_EXTENSIONS_UI_EXPORT void neph_extensions_ui_answer(int32_t id,
                                                         int32_t result);
int neph_extensions_ui_installed(const char* json);
}  // extern "C"

namespace {

std::atomic<const NephExtensionsUiHooks*> g_neph_hooks{nullptr};

struct NephPendingPrompt {
  ExtensionInstallPrompt::DoneCallback done;
  std::unique_ptr<InstallPromptData> prompt;
  std::unique_ptr<ExtensionInstallPromptShowParams> show_params;
};

std::map<int32_t, NephPendingPrompt>& NephPending() {
  static base::NoDestructor<std::map<int32_t, NephPendingPrompt>> pending;
  return *pending;
}

int32_t g_neph_next_prompt = 0;

const char* NephPromptType(InstallPromptData::PromptType type) {
  switch (type) {
    case InstallPromptData::INSTALL_PROMPT:
      return "install";
    case InstallPromptData::RE_ENABLE_PROMPT:
      return "re-enable";
    case InstallPromptData::PERMISSIONS_PROMPT:
      return "permissions";
    default:
      return nullptr;
  }
}

// The question as the host shows it: the texts of Chrome's dialog, its icon.
std::string NephPromptJson(const InstallPromptData& prompt, const char* type) {
  base::DictValue dict;
  dict.Set("type", type);
  if (const extensions::Extension* extension = prompt.extension()) {
    dict.Set("extensionId", extension->id());
    dict.Set("name", extension->name());
  }
  dict.Set("title", prompt.GetDialogTitle());
  dict.Set("accept", prompt.GetAcceptButtonLabel());
  dict.Set("cancel", prompt.GetAbortButtonLabel());
  dict.Set("heading", prompt.GetPermissionsHeading());
  dict.Set("withheld", prompt.ShouldWithheldPermissionsOnDialogAccept());
  base::ListValue permissions;
  for (size_t i = 0; i < prompt.GetPermissionCount(); ++i) {
    permissions.Append(prompt.GetPermission(i));
  }
  dict.Set("permissions", std::move(permissions));
  if (!prompt.icon().IsEmpty()) {
    std::optional<std::vector<uint8_t>> png =
        gfx::PNGCodec::EncodeBGRASkBitmap(prompt.icon().AsBitmap(), false);
    if (png) {
      dict.Set("icon", "data:image/png;base64," + base::Base64Encode(*png));
    }
  }
  return base::WriteJson(dict).value_or("{}");
}

// Hands the question to the host; true when the host asks it. The question
// keeps Chrome's callback until the host's answer.
bool NephAskHost(
    std::unique_ptr<ExtensionInstallPromptShowParams>& show_params,
    ExtensionInstallPrompt::DoneCallback& done,
    std::unique_ptr<InstallPromptData>& prompt) {
  const NephExtensionsUiHooks* hooks = g_neph_hooks.load();
  if (!hooks || !hooks->prompt || !prompt ||
      prompt->requires_parent_permission()) {
    return false;
  }
  const char* type = NephPromptType(prompt->type());
  if (!type) {
    return false;
  }
  const int32_t id = ++g_neph_next_prompt;
  const std::string json = NephPromptJson(*prompt, type);
  if (hooks->prompt(id, json.c_str()) != 1) {
    return false;
  }
  prompt->OnDialogOpened();
  NephPending().emplace(
      id, NephPendingPrompt{std::move(done), std::move(prompt),
                            std::move(show_params)});
  return true;
}

}  // namespace

extern "C" NEPH_EXTENSIONS_UI_EXPORT void neph_extensions_ui_set_hooks(
    const NephExtensionsUiHooks* hooks) {
  g_neph_hooks.store(hooks && hooks->version == 1 &&
                             hooks->size >= sizeof(NephExtensionsUiHooks)
                         ? hooks
                         : nullptr);
}

// 1: accepted; 2: accepted without the withheld site access; anything else:
// cancelled. Runs on the UI thread whichever thread calls.
extern "C" NEPH_EXTENSIONS_UI_EXPORT void neph_extensions_ui_answer(
    int32_t id,
    int32_t result) {
  content::GetUIThreadTaskRunner({})->PostTask(
      FROM_HERE, base::BindOnce(
                     [](int32_t id, int32_t result) {
                       auto& pending = NephPending();
                       auto it = pending.find(id);
                       if (it == pending.end()) {
                         return;
                       }
                       NephPendingPrompt entry = std::move(it->second);
                       pending.erase(it);
                       if (result == 1 || result == 2) {
                         entry.prompt->OnDialogAccepted();
                         std::move(entry.done).Run(
                             ExtensionInstallPrompt::DoneCallbackPayload(
                                 result == 2 &&
                                         entry.prompt
                                             ->ShouldWithheldPermissionsOnDialogAccept()
                                     ? ExtensionInstallPrompt::Result::
                                           ACCEPTED_WITH_WITHHELD_PERMISSIONS
                                     : ExtensionInstallPrompt::Result::
                                           ACCEPTED));
                       } else {
                         entry.prompt->OnDialogCanceled();
                         std::move(entry.done).Run(
                             ExtensionInstallPrompt::DoneCallbackPayload(
                                 ExtensionInstallPrompt::Result::USER_CANCELED));
                       }
                     },
                     id, result));
}

extern "C" int neph_extensions_ui_installed(const char* json) {
  const NephExtensionsUiHooks* hooks = g_neph_hooks.load();
  return hooks && hooks->installed ? hooks->installed(json) : 0;
}
'''

EDITS = {
    DIALOG: [(
        '''using content::OpenURLParams;
using content::Referrer;
using extensions::InstallPromptData;
''',
        '''using content::OpenURLParams;
using content::Referrer;
using extensions::InstallPromptData;
''' + HOOKS), (
        '''    std::unique_ptr<InstallPromptData> prompt) {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);

  // If the dialog has to be parented to WebContents, force activate the''',
        '''    std::unique_ptr<InstallPromptData> prompt) {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);

  // Neph: the host asks this itself (extensions_ui_patch.py).
  if (NephAskHost(show_params, done_callback, prompt)) {
    return;
  }

  // If the dialog has to be parented to WebContents, force activate the''')],
    DESKTOP: [(
        '''#include "extensions/common/extension.h"
''',
        '''#include "extensions/common/extension.h"

// Neph (24.10.2026, Opus 5.5): defined with the install dialog
// (extension_install_dialog_view.cc); the host announces an installed
// extension itself (scripts/chromium-patches/extensions_ui_patch.py).
#include "base/json/json_writer.h"
#include "base/values.h"
extern "C" int neph_extensions_ui_installed(const char* json);
'''), (
        '''  // Extensions aren't enabled by default in incognito so we confirm
  // the install in a normal window.
  Profile* current_profile = profile()->GetOriginalProfile();''',
        '''  // Neph: the host announces the extension in its toolbar; Chrome's note
  // would open a window of its own with an empty tab for it
  // (FindOrCreateVisibleBrowser below; extensions_ui_patch.py).
  if (!extension->is_app()) {
    base::DictValue neph_note;
    neph_note.Set("id", extension->id());
    neph_note.Set("name", extension->name());
    if (neph_extensions_ui_installed(
            base::WriteJson(neph_note).value_or("{}").c_str()) == 1) {
      return;
    }
  }

  // Extensions aren't enabled by default in incognito so we confirm
  // the install in a normal window.
  Profile* current_profile = profile()->GetOriginalProfile();''')],
}


def build(path, text):
    """text: the committed file. Returns the patched file."""
    if MARK in text or 'extensions_ui_patch.py' in text:
        raise AnchorMissing(path + ': already patched (expected the committed text)')
    for old, new in EDITS[path]:
        text = replace_once(text, old, new, path)
    return text
