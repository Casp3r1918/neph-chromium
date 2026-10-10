#!/usr/bin/env python3
"""Neph's patches for the Chromium tree, applied before the CEF build.

Usage:  python apply.py <path to chromium/src> [--lenient]
        python apply.py <path to chromium/src> --revert

Run it after CEF's own patches are in the tree (scripts/cef-build.ps1 -Patch
runs cef/tools/patcher.py first). Every target file's patched content is
derived from the committed version (git show HEAD:path) and written only when
the file on disk differs, so the script is idempotent by construction: a
second run writes nothing and ninja rebuilds nothing, and an interrupted run
is simply completed by the next one. Files that one of CEF's patches touches
(cef/patch/patches/*.patch) are never modified, because CEF's patcher checks
its patches by context and would report them as failed. Exit 0 when the tree
is in the patched state, 1 when an anchor was not found (the tree differs
from what a patch expects: inspect, do not build), 2 on usage errors.

--revert restores the committed content of every file this script may
touch (the fixed files, the string tables with their parts and translations,
the ANGLE file in its nested repository; CEF's own patched files are left to
CEF's patch updater). scripts/cef-build.ps1 -Sync runs it before
automate-git --fast-update, which refuses a Chromium checkout with changes
that are not in a CEF patch file.

Mandatory and optional. The widevine patch is mandatory: without it the
browser would fetch a CDM it has no licence for, so a missing anchor always
stops the build. So is the vault patch: without it saved passwords stay under
the key any process of the user can unwrap, whatever the settings page says.
Everything else (mv2, branding, the three shader patches, downloads, zoom_steps, page_base) is optional: with --lenient a missing anchor is logged, listed under
"optional_failed" in neph-patches.json and the build goes on, so a security
update never waits for a cosmetic anchor. Without --lenient every anchor is
fatal, which is what a hand-run wants.

Patches
  mv2       extensions/browser/manifest_v2_handler.cc: Manifest V2 extensions
            stay installable and enabled. Chromium 152 keeps one switch for
            its own tests (g_allow_mv2_for_testing); it becomes the default.
            The manifest parser itself still accepts version 2 (extension.cc,
            kMinimumSupportedManifestVersion = 2), so nothing else is needed.
  branding  chrome/app/theme/chromium/BRANDING plus the string tables whose
            messages name the product literally (chromium_strings, generated
            resources, components, privacy sandbox, extensions) and their
            .xtb translations: the product is called "Neph" in every dialog.
            Only message text changes (not descriptions or comments). The
            translation ids in the .xtb files are fingerprints of the English
            text, so after the English changed they are recomputed with
            Chromium's own grit (parsed from temporary mirrors of the sources
            before and after) and renamed in the .xtb files; only those
            renamed translations get the new name, every other translation
            stays as it is. Without that every affected message would fall
            back to English. What keeps saying Chromium: the copyright line
            and company name (IDS_ABOUT_VERSION_COPYRIGHT/_COMPANY_NAME, in
            every language), the link text of the Chromium open source project
            in the licence line, "The Chromium Authors", "Chromium OS",
            "Chromium Embedded", and components/version_ui_strings.grdp (CEF
            patches it; chrome://version gets Neph's own page).

  page_base chrome/browser/ui/views/frame/contents_web_view.cc: the page's
            view stays opaque when CEF hides its background, so pages without
            a background of their own are white instead of the dark theme
            colour behind them (06.10.2026).
  program_cache  gpu/config/gpu_preferences.h: the GPU program cache holds
            64 MB instead of 6 MB (memory and disk; Skia shares the value).
  cache_scope    gpu/ipc/service/command_buffer_stub.cc: the program-cache
            scope that forwards ANGLE's linked binaries to the disk cache is
            created before MakeCurrent(), where the program-completion queries
            are processed and the binaries are handed over. Without it every
            program whose link completion was seen there stayed memory-only
            and compiled again on every start.
  vault     components/password_manager/core/browser/password_store/
            login_database{_win.cc,.cc,.h}: saved passwords are encrypted by the
            host's vault (master password + TPM-sealed device secret) instead of
            the OS key; the old blobs are converted by neph_vault_migrate; the
            store never deletes "undecryptable" passwords. Details and the ABI
            in vault_patch.py and src/native/vault_hooks.h.
  widevine       chrome/browser/component_updater/registration.cc: the
            Widevine CDM component is registered (and so downloaded) only
            when the browser process carries --neph-widevine. Without a
            licence agreement Neph neither ships nor fetches the CDM; the
            host sets the switch only for the hidden setting system.widevine.
  mrt_layout     third_party/angle/.../ProgramExecutableD3D.cpp: the default
            pixel output layout lists every declared output location, so a
            program with several colour outputs is not compiled a second time
            (blocking the GPU process) at its first draw.
  downloads cef/libcef/browser/download_manager_delegate_impl.cc (in the
            nested CEF checkout): downloads whose browser was destroyed keep
            reporting to another browser of a client with a download handler,
            and partial files grow as "<name>.crdownload". libcef.dll exports
            neph_downloads_patch_level(). And
            chrome/browser/download/download_core_service.cc: closing a tab no
            longer cancels every download (CEF's one Browser per tab looks
            like the last window). Details in downloads_patch.py.
The script writes neph-patches.json next to the tree with what it did.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

import downloads_patch
import vault_patch

PRODUCT = 'Neph'
# The product name as a word, except where it names the project or a
# different product: the authors, Chromium OS, CEF, and the link text of the
# Chromium open source project ("...<ph name="BEGIN_LINK_CHROMIUM">Chromium
# <ph name="END_LINK_CHROMIUM">" in grd and xtb alike). Other link texts
# ("sign in to <link>Chromium</link>") are the product and do change.
WORD = re.compile(r'\bChromium\b(?! Authors\b| OS\b| Embedded\b|<ph name="END_LINK_CHROMIUM)')
KEEP_MESSAGES = {'IDS_ABOUT_VERSION_COPYRIGHT', 'IDS_ABOUT_VERSION_COMPANY_NAME'}
MESSAGE = re.compile(r'(<message\b[^>]*>)(.*?)(</message>)', re.S)
TRANSLATION = re.compile(r'(<translation\s+id=")(\d+)(">)(.*?)(</translation>)', re.S)

MV2_FILE = 'extensions/browser/manifest_v2_handler.cc'
MV2_OLD = 'bool g_allow_mv2_for_testing = false;'
MV2_NEW = ('bool g_allow_mv2_for_testing = true;'
           '  // Neph: Manifest V2 stays supported.')
# Page zoom in finer steps (06.10.2026): Chromium jumps 100 -> 110 -> 125 ->
# 150; the user asked for a smoother zoom. Both the keyboard and Ctrl+wheel
# take their steps from this list, so the change has to live in the core.
ZOOM_FILE = 'third_party/blink/common/page/page_zoom.cc'
ZOOM_OLD = ('static constexpr double kPresetBrowserZoomFactorsArray[] = {\n'
            '    0.25, 1 / 3.0, 0.5,  2 / 3.0, 0.75, 0.8, 0.9, 1.0, 1.1,\n'
            '    1.25, 1.5,     1.75, 2.0,     2.5,  3.0, 4.0, 5.0};')
ZOOM_NEW = ('static constexpr double kPresetBrowserZoomFactorsArray[] = {\n'
            '    0.25, 1 / 3.0, 0.5,  2 / 3.0, 0.75, 0.8, 0.9,  1.0, 1.05, 1.1,\n'
            '    1.15, 1.2,     1.25, 1 / .75, 1.4,  1.5, 1.75, 2.0, 2.5,  3.0,\n'
            '    4.0,  5.0};  // Neph: finer steps between 100 and 150 percent')
# page_base (06.10.2026): CEF hides the contents view's background for
# Chrome-style browsers (chrome_browser_host_impl.cc), and the view then tells
# the renderer to be transparent: a page without a background of its own
# showed Chrome's themed MultiContentsBackgroundView - dark grey in Neph's
# dark colour scheme, under the page's dark text ("on many websites you can
# hardly read the text"). Opaque, the renderer paints the page base colour
# CEF sets from CefBrowserSettings.background_color (white in Neph).
PAGE_BASE_FILE = 'chrome/browser/ui/views/frame/contents_web_view.cc'
PAGE_BASE_OLD = ('      rwhv->SetBackgroundColor(background_visible_ ? color\n'
                 '                                                   : SK_ColorTRANSPARENT);\n')
PAGE_BASE_NEW = ('      // Neph: opaque even when the embedder hides this view\'s background,\n'
                 '      // so a page without its own background shows the page base colour\n'
                 '      // instead of the themed background behind it.\n'
                 '      rwhv->SetBackgroundColor(background_visible_ ? color : SK_ColorWHITE);\n')
BRANDING = 'chrome/app/theme/chromium/BRANDING'
# The GPU process keeps compiled programs in a cache of 6 MB; Neph's six sky
# programs are about that size together, so the largest were evicted and
# compiled again on every start (30 s). 64 MB holds them with room to spare.
CACHE_FILE = 'gpu/config/gpu_preferences.h'
CACHE_OLD = 'const size_t kDefaultMaxProgramCacheMemoryBytes = 6 * 1024 * 1024;'
CACHE_NEW = ('const size_t kDefaultMaxProgramCacheMemoryBytes = 64 * 1024 * 1024;'
             '  // Neph: room for the sky shaders (was 6 MB)')
# The passthrough decoder resolves a finished link when it processes the
# program-completion query, and ANGLE hands the linked binary to Chromium's
# blob cache right there. Chromium forwards blobs to the disk cache only while
# a ScopedCacheUse is active, but the queries are processed inside
# MakeCurrent(), which PerformWork and ScopedContextOperation both call before
# they create that scope: the binary of every program whose completion was
# seen that way stayed in memory, the disk cache never got it, and the sky
# compiled again on every start (measured 24.09.2026, docs/rendering.md).
SCOPE_FILE = 'gpu/ipc/service/command_buffer_stub.cc'
SCOPE_OLD_1 = ('  if (decoder_context_.get() && !MakeCurrent())\n'
               '    return;\n'
               '  std::optional<gles2::ProgramCache::ScopedCacheUse> cache_use;\n'
               '  CreateCacheUse(cache_use);\n')
SCOPE_NEW_1 = ('  // Neph: the cache scope before MakeCurrent(), which processes the pending\n'
               '  // program-completion queries; ANGLE caches the linked binary right there.\n'
               '  std::optional<gles2::ProgramCache::ScopedCacheUse> cache_use;\n'
               '  CreateCacheUse(cache_use);\n'
               '  if (decoder_context_.get() && !MakeCurrent())\n'
               '    return;\n')
SCOPE_OLD_2 = ('  if (stub_.decoder_context_ && stub_.MakeCurrent()) {\n'
               '    have_context_ = true;\n'
               '    stub_.CreateCacheUse(cache_use_);\n'
               '  }\n')
SCOPE_NEW_2 = ('  if (stub_.decoder_context_) {\n'
               '    // Neph: see PerformWork - the scope has to cover MakeCurrent().\n'
               '    stub_.CreateCacheUse(cache_use_);\n'
               '    if (stub_.MakeCurrent()) {\n'
               '      have_context_ = true;\n'
               '    } else {\n'
               '      cache_use_.reset();\n'
               '    }\n'
               '  }\n')
# ANGLE's D3D11 backend compiles the pixel executable at link time for the
# layout derived from the shader, which held only the first output location.
# A program that writes several colour attachments then got a second, blocking
# compile of the same pixel shader at its first draw (the sky's cloud pass:
# about 22 s with the whole GPU process, i.e. every window, frozen). The
# default layout now lists every declared output location.
MRT_REPO = 'third_party/angle'  # a nested git checkout; pristine text from its own HEAD
MRT_FILE = 'third_party/angle/src/libANGLE/renderer/d3d/ProgramExecutableD3D.cpp'
MRT_OLD = ('    outputLayoutOut->clear();\n'
           '\n'
           '    if (!shaderOutputVars.empty())\n'
           '    {\n'
           '        size_t location = shaderOutputVars[0].outputLocation;\n'
           '        size_t maxIndex = GetMaxOutputIndex(shaderOutputVars, location);\n'
           '        outputLayoutOut->assign(maxIndex + 1,\n'
           '                                GL_COLOR_ATTACHMENT0 + static_cast<unsigned int>(location));\n'
           '    }\n')
MRT_NEW = ('    outputLayoutOut->clear();\n'
           '    if (shaderOutputVars.empty())\n'
           '    {\n'
           '        return;\n'
           '    }\n'
           '    // Neph: one entry per declared output location (GL_NONE for gaps), so a\n'
           '    // program writing several colour attachments gets the pixel executable\n'
           '    // for that layout at link time instead of a second, blocking compile at\n'
           '    // its first draw.\n'
           '    size_t maxLocation = 0;\n'
           '    for (const PixelShaderOutputVariable &outputVar : shaderOutputVars)\n'
           '    {\n'
           '        if (outputVar.outputLocation > maxLocation)\n'
           '        {\n'
           '            maxLocation = outputVar.outputLocation;\n'
           '        }\n'
           '    }\n'
           '    for (size_t location = 0; location <= maxLocation; ++location)\n'
           '    {\n'
           '        bool declared = false;\n'
           '        for (const PixelShaderOutputVariable &outputVar : shaderOutputVars)\n'
           '        {\n'
           '            declared = declared || outputVar.outputLocation == location;\n'
           '        }\n'
           '        if (!declared)\n'
           '        {\n'
           '            outputLayoutOut->push_back(GL_NONE);\n'
           '            continue;\n'
           '        }\n'
           '        size_t maxIndex = GetMaxOutputIndex(shaderOutputVars, location);\n'
           '        outputLayoutOut->insert(outputLayoutOut->end(), maxIndex + 1,\n'
           '                                GL_COLOR_ATTACHMENT0 + static_cast<unsigned int>(location));\n'
           '    }\n')
WIDEVINE_FILE = 'chrome/browser/component_updater/registration.cc'
WIDEVINE_INC_OLD = '#include "base/feature_list.h"\n'
WIDEVINE_INC_NEW = '#include "base/command_line.h"\n#include "base/feature_list.h"\n'
WIDEVINE_OLD = ('#if BUILDFLAG(ENABLE_WIDEVINE_CDM_COMPONENT)\n'
                '  RegisterWidevineCdmComponent(cus);\n'
                '#endif  // BUILDFLAG(ENABLE_WIDEVINE_CDM_COMPONENT)\n')
WIDEVINE_NEW = ('#if BUILDFLAG(ENABLE_WIDEVINE_CDM_COMPONENT)\n'
                '  // Neph: the Widevine CDM is licensed software; without an agreement the\n'
                '  // browser neither ships nor fetches it. The component updater learns\n'
                '  // about it only when the host asks with --neph-widevine.\n'
                '  if (base::CommandLine::ForCurrentProcess()->HasSwitch("neph-widevine"))\n'
                '    RegisterWidevineCdmComponent(cus);\n'
                '#endif  // BUILDFLAG(ENABLE_WIDEVINE_CDM_COMPONENT)\n')
GRDS = ['chrome/app/chromium_strings.grd',
        'components/components_chromium_strings.grd',
        'chrome/app/generated_resources.grd',
        'components/components_strings.grd',
        'components/privacy_sandbox_strings.grd',
        'extensions/strings/extensions_strings.grd']
IDS_SPEC = 'tools/gritsettings/resource_ids.spec'


class Anchor(Exception):
    pass


def log(msg):
    print(time.strftime('%H:%M:%S'), msg, flush=True)


def rel(path):
    return path.replace('\\', '/')


def pristine(src, path):
    """The committed content of a file, as text."""
    r = subprocess.run(['git', '-C', src, 'show', 'HEAD:' + path],
                       capture_output=True)
    if r.returncode != 0:
        raise SystemExit('git show failed for %s: %s' %
                         (path, r.stderr.decode('utf-8', 'replace').strip()))
    return r.stdout.decode('utf-8')


def on_disk(src, path):
    with open(os.path.join(src, path), 'rb') as f:
        return f.read().decode('utf-8')


def put(src, path, text, written):
    """Write text to path only when the file differs; count what changed."""
    data = text.encode('utf-8')
    p = os.path.join(src, path)
    with open(p, 'rb') as f:
        if f.read() == data:
            return False
    with open(p, 'wb') as f:
        f.write(data)
    written.append(path)
    return True


def cef_patched_files(src):
    """Every file one of CEF's patches modifies (paths relative to src)."""
    files = set()
    for p in glob.glob(os.path.join(src, 'cef', 'patch', 'patches', '*.patch')):
        with open(p, 'rb') as f:
            for line in f.read().decode('utf-8', 'replace').splitlines():
                if line.startswith('+++ '):
                    path = line[4:].strip()
                    if path.startswith('b/'):
                        path = path[2:]
                    files.add(rel(path))
    return files


def rename_product(text):
    """The product name in message text only; kept messages stay verbatim."""
    def block(m):
        name = re.search(r'\bname="([^"]+)"', m.group(1))
        if name and name.group(1) in KEEP_MESSAGES:
            return m.group(0)
        return m.group(1) + WORD.sub(PRODUCT, m.group(2)) + m.group(3)
    return MESSAGE.sub(block, text)


def message_ids(src, grd, texts, mirror):
    """[(name, id)] of every <message> in document order, as grit computes
    it for the given texts, parsed from a temporary mirror of the tree."""
    for path, text in texts.items():
        p = os.path.join(mirror, path)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'wb') as f:
            f.write(text.encode('utf-8'))
    spec = os.path.join(src, IDS_SPEC)
    if os.path.exists(spec):
        target = os.path.join(mirror, IDS_SPEC)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(spec, target)
    grit_dir = os.path.join(src, 'tools', 'grit')
    if grit_dir not in sys.path:
        sys.path.insert(0, grit_dir)
    from grit import grd_reader
    from grit.node import message as message_node
    root = grd_reader.Parse(os.path.join(mirror, grd), target_platform='win32',
                            skip_validation_checks=True)
    out = []

    def walk(node):
        if isinstance(node, message_node.MessageNode):
            cliques = node.GetCliques()
            if cliques:
                out.append((node.attrs['name'], str(cliques[0].GetId())))
        for child in node.children:
            walk(child)

    walk(root)
    return out


def patch_widevine(src, written, protected):
    if WIDEVINE_FILE in protected:
        raise Anchor(WIDEVINE_FILE + ': touched by a CEF patch')
    text = pristine(src, WIDEVINE_FILE)
    if WIDEVINE_OLD not in text or WIDEVINE_INC_OLD not in text:
        raise Anchor(WIDEVINE_FILE + ': ' + WIDEVINE_OLD.splitlines()[1])
    text = text.replace(WIDEVINE_INC_OLD, WIDEVINE_INC_NEW, 1).replace(WIDEVINE_OLD, WIDEVINE_NEW, 1)
    return 'written' if put(src, WIDEVINE_FILE, text, written) else 'in place'


def patch_vault(src, written, protected):
    for path in vault_patch.FILES:
        if path in protected:
            raise Anchor(path + ' is CEF-patched now; move the vault patch')
    try:
        built = vault_patch.build({path: pristine(src, path) for path in vault_patch.FILES})
    except vault_patch.AnchorMissing as e:
        raise Anchor(str(e))
    changed = [path for path, text in built.items() if put(src, path, text, written)]
    return 'written' if changed else 'in place'


def patch_downloads(src, written, protected):
    for path in (downloads_patch.FILE, downloads_patch.CHROME_FILE):
        if path in protected:
            raise Anchor(path + ' is CEF-patched now; move the downloads patch')
    try:
        text = downloads_patch.build(pristine_nested(src, downloads_patch.REPO, downloads_patch.PATH))
        chrome = downloads_patch.build_chrome(pristine(src, downloads_patch.CHROME_FILE))
    except downloads_patch.AnchorMissing as e:
        raise Anchor(str(e))
    changed = [put(src, downloads_patch.FILE, text, written), put(src, downloads_patch.CHROME_FILE, chrome, written)]
    return 'written' if any(changed) else 'in place'


def patch_mv2(src, written):
    text = pristine(src, MV2_FILE)
    if MV2_OLD not in text:
        raise Anchor(MV2_FILE + ': ' + MV2_OLD)
    return 'written' if put(src, MV2_FILE, text.replace(MV2_OLD, MV2_NEW, 1), written) else 'in place'


def patch_zoom_steps(src, written, protected):
    if ZOOM_FILE in protected:
        raise Anchor(ZOOM_FILE + ' is CEF-patched now; move the zoom steps change')
    text = read_current(src, ZOOM_FILE)
    if ZOOM_NEW in text:
        return 'in place'
    if ZOOM_OLD not in text:
        raise Anchor(ZOOM_FILE + ': ' + ZOOM_OLD.splitlines()[0])
    return 'written' if put(src, ZOOM_FILE, text.replace(ZOOM_OLD, ZOOM_NEW, 1), written) else 'in place'


def patch_page_base(src, written, protected):
    if PAGE_BASE_FILE in protected:
        raise Anchor(PAGE_BASE_FILE + ' is CEF-patched now; move the page base change')
    text = read_current(src, PAGE_BASE_FILE)
    if PAGE_BASE_NEW in text:
        return 'in place'
    if PAGE_BASE_OLD not in text:
        raise Anchor(PAGE_BASE_FILE + ': ' + PAGE_BASE_OLD.splitlines()[0].strip())
    return 'written' if put(src, PAGE_BASE_FILE, text.replace(PAGE_BASE_OLD, PAGE_BASE_NEW, 1), written) else 'in place'


def patch_program_cache(src, written, protected):
    if CACHE_FILE in protected:
        raise Anchor(CACHE_FILE + ' is CEF-patched now; move the cache change')
    text = read_current(src, CACHE_FILE)
    if CACHE_NEW in text:
        return 'in place'
    if CACHE_OLD not in text:
        raise Anchor(CACHE_FILE + ': ' + CACHE_OLD)
    return 'written' if put(src, CACHE_FILE, text.replace(CACHE_OLD, CACHE_NEW, 1), written) else 'in place'


def patch_cache_scope(src, written, protected):
    if SCOPE_FILE in protected:
        raise Anchor(SCOPE_FILE + ' is CEF-patched now; move the cache scope change')
    text = read_current(src, SCOPE_FILE)
    if SCOPE_NEW_1 in text and SCOPE_NEW_2 in text:
        return 'in place'
    for old in (SCOPE_OLD_1, SCOPE_OLD_2):
        if old not in text:
            raise Anchor(SCOPE_FILE + ': ' + old.strip().splitlines()[0])
    text = text.replace(SCOPE_OLD_1, SCOPE_NEW_1, 1).replace(SCOPE_OLD_2, SCOPE_NEW_2, 1)
    return 'written' if put(src, SCOPE_FILE, text, written) else 'in place'


def patch_mrt_layout(src, written, protected):
    if MRT_FILE in protected:
        raise Anchor(MRT_FILE + ' is CEF-patched now; move the layout change')
    text = pristine_nested(src, MRT_REPO, MRT_FILE[len(MRT_REPO) + 1:])
    if MRT_NEW in text:
        return 'in place'
    if MRT_OLD not in text:
        raise Anchor(MRT_FILE + ': GetDefaultOutputLayoutFromShader body')
    return 'written' if put(src, MRT_FILE, text.replace(MRT_OLD, MRT_NEW, 1), written) else 'in place'


def pristine_nested(src, repo, path):
    """The committed content of a file inside a nested checkout (a DEPS
    dependency with its own .git), as text."""
    return pristine(os.path.join(src, repo), path)


def read_current(src, path):
    return pristine(src, path)


def patch_branding_file(src, written):
    text = pristine(src, BRANDING)
    new = re.sub(r'^(PRODUCT_(?:FULLNAME|SHORTNAME|INSTALLER_FULLNAME|'
                 r'INSTALLER_SHORTNAME))=Chromium', r'\1=' + PRODUCT, text,
                 flags=re.M)
    if new == text:
        raise Anchor(BRANDING + ': PRODUCT_*=Chromium')
    return 'written' if put(src, BRANDING, new, written) else 'in place'


def patch_strings(src, grd, written, tmp, protected):
    """One grd with its parts and translations."""
    # Sources: committed text, or the file as it is for CEF-patched parts.
    texts = {}
    parts, xtbs, todo = [], [], [grd]
    while todo:
        f = todo.pop(0)
        texts[f] = on_disk(src, f) if f in protected else pristine(src, f)
        base = os.path.dirname(f)
        for m in re.findall(r'<part\s+file="([^"]+)"', texts[f]):
            p = rel(os.path.normpath(os.path.join(base, m)))
            if p not in texts and p not in todo:
                parts.append(p)
                todo.append(p)
        for m in re.findall(r'<file\s+path="([^"]+\.xtb)"', texts[f]):
            xtbs.append(rel(os.path.normpath(os.path.join(base, m))))
    new_texts = {p: (t if p in protected else rename_product(t))
                 for p, t in texts.items()}
    changed = [p for p in texts if new_texts[p] != texts[p]]
    idmap = {}
    if changed:
        before = message_ids(src, grd, texts, os.path.join(tmp, 'old'))
        after = message_ids(src, grd, new_texts, os.path.join(tmp, 'new'))
        if [n for n, _ in before] != [n for n, _ in after]:
            raise SystemExit('message list differs after the text change: ' + grd)
        idmap = {a: b for (_, a), (_, b) in zip(before, after) if a != b}
    renamed = 0
    xtb_written = 0
    for f in xtbs:
        if f in protected:
            continue
        text = pristine(src, f)
        count = [0]

        def translation(m):
            new_id = idmap.get(m.group(2))
            if new_id is None:
                return m.group(0)
            count[0] += 1
            return m.group(1) + new_id + m.group(3) + WORD.sub(PRODUCT, m.group(4)) + m.group(5)

        new = TRANSLATION.sub(translation, text) if idmap else text
        if put(src, f, new, written):
            xtb_written += 1
        renamed += count[0]
    sources_written = 0
    for p in parts + [grd]:
        if p in protected:
            continue
        if put(src, p, new_texts[p], written):
            sources_written += 1
    return {'sources_changed': len(changed), 'sources_written': sources_written,
            'messages': len(before) if changed else 0, 'ids_changed': len(idmap),
            'xtb_files': len(xtbs), 'xtb_written': xtb_written,
            'translations_renamed': renamed,
            'cef_files_left': sorted(p for p in texts if p in protected)}


def touched_paths(src, protected):
    """Every path (relative to src) a run of this script may write, from
    the committed string tables: the grd files, their parts, their xtb
    translations, plus the fixed files. CEF-patched files are excluded."""
    paths = []
    for p in (MV2_FILE, BRANDING, CACHE_FILE, SCOPE_FILE, ZOOM_FILE, PAGE_BASE_FILE, WIDEVINE_FILE, downloads_patch.CHROME_FILE) + vault_patch.FILES:
        if p not in protected:
            paths.append(p)
    for grd in GRDS:
        if not os.path.exists(os.path.join(src, grd)):
            continue
        todo = [grd]
        while todo:
            f = todo.pop(0)
            if f in paths or f in protected:
                continue
            paths.append(f)
            text = pristine(src, f)
            base = os.path.dirname(f)
            for m in re.findall(r'<part\s+file="([^"]+)"', text):
                p = rel(os.path.normpath(os.path.join(base, m)))
                if p not in paths and p not in todo:
                    todo.append(p)
            for m in re.findall(r'<file\s+path="([^"]+\.xtb)"', text):
                p = rel(os.path.normpath(os.path.join(base, m)))
                if p not in paths and p not in protected:
                    paths.append(p)
    return paths


def revert(src):
    protected = cef_patched_files(src)
    paths = touched_paths(src, protected)
    spec = os.path.join(tempfile.gettempdir(), 'neph-revert-%d.txt' % os.getpid())
    with open(spec, 'w', encoding='utf-8') as f:
        f.write('\n'.join(paths) + '\n')
    try:
        r = subprocess.run(['git', '-C', src, 'checkout', '--pathspec-from-file=' + spec],
                           capture_output=True)
    finally:
        os.unlink(spec)
    if r.returncode != 0:
        raise SystemExit('git checkout failed: ' + r.stderr.decode('utf-8', 'replace').strip())
    r = subprocess.run(['git', '-C', os.path.join(src, MRT_REPO), 'checkout', '--',
                        MRT_FILE[len(MRT_REPO) + 1:]], capture_output=True)
    if r.returncode != 0:
        raise SystemExit('git checkout in %s failed: %s' %
                         (MRT_REPO, r.stderr.decode('utf-8', 'replace').strip()))
    r = subprocess.run(['git', '-C', os.path.join(src, downloads_patch.REPO), 'checkout', '--',
                        downloads_patch.PATH], capture_output=True)
    if r.returncode != 0:
        raise SystemExit('git checkout in %s failed: %s' %
                         (downloads_patch.REPO, r.stderr.decode('utf-8', 'replace').strip()))
    report = os.path.join(src, 'neph-patches.json')
    if os.path.exists(report):
        os.remove(report)
    log('reverted: %d paths restored to their committed content (plus %s and %s)' %
        (len(paths), MRT_FILE, downloads_patch.FILE))
    return 0


def main(argv):
    lenient = '--lenient' in argv[1:]
    args = [a for a in argv[1:] if not a.startswith('--')]
    unknown = [a for a in argv[1:] if a.startswith('--') and a not in ('--lenient', '--revert')]
    if unknown or len(args) != 1 or not os.path.isdir(os.path.join(args[0], 'chrome')):
        print(__doc__)
        return 2
    src = os.path.abspath(args[0])
    if '--revert' in argv[1:]:
        return revert(src)
    protected = cef_patched_files(src)
    log('%d files belong to CEF patches and stay untouched' % len(protected))
    written = []
    report = {'src': src, 'when': time.strftime('%Y-%m-%d %H:%M:%S'),
              'product': PRODUCT, 'lenient': lenient, 'patches': {},
              'optional_failed': []}
    tmp = tempfile.mkdtemp(prefix='neph-grit-')

    def optional(name, fn):
        """An optional patch: a missing anchor is fatal unless --lenient."""
        try:
            report['patches'][name] = fn()
        except Anchor as e:
            if not lenient:
                raise
            log('WARNING optional patch %s skipped: %s' % (name, e))
            report['patches'][name] = 'failed: %s' % e
            report['optional_failed'].append(name)

    try:
        optional('mv2', lambda: patch_mv2(src, written))
        optional('branding_file', lambda: patch_branding_file(src, written))
        optional('program_cache', lambda: patch_program_cache(src, written, protected))
        optional('cache_scope', lambda: patch_cache_scope(src, written, protected))
        optional('mrt_layout', lambda: patch_mrt_layout(src, written, protected))
        optional('zoom_steps', lambda: patch_zoom_steps(src, written, protected))
        optional('page_base', lambda: patch_page_base(src, written, protected))
        optional('downloads', lambda: patch_downloads(src, written, protected))
        # Mandatory, whatever the mode: see the module docstring.
        report['patches']['widevine'] = patch_widevine(src, written, protected)
        report['patches']['vault'] = patch_vault(src, written, protected)
        for grd in GRDS:
            if not os.path.exists(os.path.join(src, grd)):
                log('missing, skipped: ' + grd)
                report['patches'][grd] = 'missing'
                if lenient:
                    report['optional_failed'].append(grd)
                continue
            optional(grd, lambda grd=grd: patch_strings(
                src, grd, written, os.path.join(tmp, grd.replace('/', '_')),
                protected))
            log('%s: %s' % (grd, json.dumps(report['patches'][grd])))
    except Anchor as e:
        log('ANCHOR NOT FOUND: %s' % e)
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    report['files_written'] = len(written)
    with open(os.path.join(src, 'neph-patches.json'), 'w',
              encoding='utf-8') as f:
        json.dump(report, f, indent=1)
    log('done, files written: %d' % len(written))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
