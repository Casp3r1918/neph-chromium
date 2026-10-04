"""The "downloads" patch of apply.py: CEF's download manager delegate.

Neph decides where a download goes (CefDownloadHandler::OnBeforeDownload)
and shows its progress from OnDownloadUpdated. Two things in CEF's delegate
stand in the way (cef/libcef/browser/download_manager_delegate_impl.cc):

1. When the browser that started a download is destroyed (the tab closes, or
   it was opened for the download alone), CEF stops calling the download
   handler: the download goes on silently and the client never learns that
   it finished. The patch hands such downloads to another browser whose client
   handles downloads, one of the same profile when there is one, so the
   updates keep coming. Without any such browser it behaves as before.

2. The file grows under its final name (CEF sets the intermediate path to the
   target path). Chrome writes "<name>.crdownload" and renames it when the
   download is complete; the patch does the same for every target CEF's
   callback determines, so a partial file never looks like a finished one.
   The forced path of the Alloy bootstrap stays as it is (its temporary file
   already has that name).

3. Closing any tab cancelled every download of the profile. CEF gives each
   tab a Chrome Browser of its own, none of them ever counts as activated, so
   Browser::~Browser (UnloadController::OkToCloseWithInProgressDownloads,
   IsLastWindow) takes the close of a tab for the end of the browser and calls
   DownloadCoreService::CancelAllDownloads(kShutdown) - its only caller with
   that trigger. The patch makes that call a no-op
   (chrome/browser/download/download_core_service.cc); at the real end
   DownloadManagerImpl::Shutdown cancels what still runs, as before.

The file lives in the nested CEF checkout (src/cef, a git repository of its
own); its pristine text comes from that repository's HEAD. libcef.dll exports
neph_downloads_patch_level() so the host can tell a patched core from an
older one.
"""

REPO = 'cef'
PATH = 'libcef/browser/download_manager_delegate_impl.cc'
FILE = REPO + '/' + PATH
# In the Chromium repository itself (no CEF patch touches it).
CHROME_FILE = 'chrome/browser/download/download_core_service.cc'


class AnchorMissing(Exception):
    pass


def replace_once(text, old, new, what):
    if text.count(old) != 1:
        raise AnchorMissing('%s: %s (found %d times)' % (what, old.strip().splitlines()[0], text.count(old)))
    return text.replace(old, new, 1)


MARK = 'neph_downloads_patch_level'

INCLUDE_OLD = '#include "cef/libcef/browser/browser_host_base.h"\n'
INCLUDE_NEW = ('#include "cef/libcef/browser/browser_host_base.h"\n'
               '#include "cef/libcef/browser/browser_info.h"\n'
               '#include "cef/libcef/browser/browser_info_manager.h"\n')

TARGET_OLD = '''void RunDownloadTargetCallback(download::DownloadTargetCallback callback,
                               const base::FilePath& path) {
  download::DownloadTargetInfo target_info;
  target_info.target_path = path;
  target_info.intermediate_path = path;
  std::move(callback).Run(std::move(target_info));
}
'''
TARGET_NEW = TARGET_OLD + '''
// Neph: like Chrome, the file grows under "<name>.crdownload" and gets its
// name when it is complete, so a partial file never looks like a finished
// one. An empty path cancels the download and stays empty.
void RunNephDownloadTargetCallback(download::DownloadTargetCallback callback,
                                   const base::FilePath& path) {
  download::DownloadTargetInfo target_info;
  target_info.target_path = path;
  if (!path.empty()) {
    target_info.intermediate_path =
        base::FilePath(path.value() + FILE_PATH_LITERAL(".crdownload"));
  }
  std::move(callback).Run(std::move(target_info));
}

// Neph: the browser that takes over the downloads of |gone|: a valid one whose
// client handles downloads, of |context| when there is one.
CefRefPtr<CefBrowserHostBase> NephDownloadHeir(
    CefBrowserHostBase* gone,
    content::BrowserContext* context) {
  CefRefPtr<CefBrowserHostBase> fallback;
  for (const auto& info :
       CefBrowserInfoManager::GetInstance()->GetBrowserInfoList()) {
    if (!info->IsValid()) {
      continue;
    }
    CefRefPtr<CefBrowserHostBase> candidate = info->browser();
    if (!candidate || candidate.get() == gone ||
        !GetDownloadHandler(candidate)) {
      continue;
    }
    if (candidate->GetBrowserContext() == context) {
      return candidate;
    }
    if (!fallback) {
      fallback = candidate;
    }
  }
  return fallback;
}
'''

CHOOSE_OLD = '''    if (!handled) {
      RunDownloadTargetCallback(std::move(callback), suggested_path);
    }'''
CHOOSE_NEW = '''    if (!handled) {
      RunNephDownloadTargetCallback(std::move(callback), suggested_path);
    }'''

PICKED_OLD = '''    // The download will be cancelled if |path| is empty.
    RunDownloadTargetCallback(std::move(callback), path);'''
PICKED_NEW = '''    // The download will be cancelled if |path| is empty.
    RunNephDownloadTargetCallback(std::move(callback), path);'''

DESTROYED_OLD = '''void CefDownloadManagerDelegateImpl::OnBrowserDestroyed(
    CefBrowserHostBase* browser) {
  for (auto& [item, item_browser] : item_browser_map_) {
    if (item_browser == browser) {
      // Don't call back into browsers that have been destroyed. We're not
      // canceling the download so it will continue silently until it completes
      // or until the associated browser context is destroyed.
      item_browser = nullptr;
    }
  }
}
'''
DESTROYED_NEW = '''void CefDownloadManagerDelegateImpl::OnBrowserDestroyed(
    CefBrowserHostBase* browser) {
  // Neph: don't call back into browsers that have been destroyed, but don't
  // let their downloads go silent either: another browser whose client handles
  // downloads takes them over, so the client keeps seeing their progress and
  // their end. Without one they continue silently until they complete or the
  // browser context is destroyed.
  CefRefPtr<CefBrowserHostBase> heir;
  bool looked = false;
  for (auto& [item, item_browser] : item_browser_map_) {
    if (item_browser == browser) {
      if (!looked) {
        looked = true;
        heir = NephDownloadHeir(
            browser, content::DownloadItemUtils::GetBrowserContext(item));
      }
      item_browser = heir.get();
    }
  }
  if (heir && !heir->HasObserver(this)) {
    heir->AddObserver(this);
  }
}

// Neph: the host checks for this export to know that downloads keep reporting
// after their browser is gone and that partial files carry ".crdownload".
extern "C" __declspec(dllexport) int neph_downloads_patch_level();
extern "C" __declspec(dllexport) int neph_downloads_patch_level() {
  return 1;
}
'''


SHUTDOWN_OLD = """void DownloadCoreService::CancelAllDownloads(CancelDownloadsTrigger trigger) {
"""
SHUTDOWN_NEW = """void DownloadCoreService::CancelAllDownloads(CancelDownloadsTrigger trigger) {
  // Neph: CEF gives every tab a Browser of its own and none counts as
  // activated, so Browser::~Browser takes the close of any tab for the end of
  // the browser and would cancel every download of the profile here. At the
  // real end DownloadManagerImpl::Shutdown cancels what still runs.
  if (trigger == CancelDownloadsTrigger::kShutdown) {
    return;
  }
"""


def build_chrome(text):
    """text: the committed download_core_service.cc. Returns the patched file."""
    if 'Neph: CEF gives every tab a Browser' in text:
        raise AnchorMissing(CHROME_FILE + ': already patched (expected the committed text)')
    return replace_once(text, SHUTDOWN_OLD, SHUTDOWN_NEW, CHROME_FILE)


def build(text):
    """text: the committed file. Returns the patched file."""
    if MARK in text:
        raise AnchorMissing(FILE + ': already contains ' + MARK + ' (expected the committed text)')
    text = replace_once(text, INCLUDE_OLD, INCLUDE_NEW, FILE)
    text = replace_once(text, TARGET_OLD, TARGET_NEW, FILE)
    text = replace_once(text, CHOOSE_OLD, CHOOSE_NEW, FILE)
    text = replace_once(text, PICKED_OLD, PICKED_NEW, FILE)
    text = replace_once(text, DESTROYED_OLD, DESTROYED_NEW, FILE)
    return text
