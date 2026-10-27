"""The "chrome_brand" patch of apply.py: Neph names Chrome in its user-agent
brand list, as Chrome does (24.10.2026, Opus 5.5).

The publisher: "wir müssen jegliche art von werbung unterbinden btw also zum
beispiel dieses google fenster" - the Chrome Web Store's box "Zu Chrome
wechseln?" and its banner "Chrome installieren". Google shows them to every
Chromium-based browser whose brand list lacks "Google Chrome"; a Chromium
build lists only "Chromium" and the GREASE brand
(embedder_support::GetUserAgentBrandList, CHROMIUM_BRANDING). That file is
CEF's (embedder_product_override.patch), so the brand joins where the list is
handed out:

  components/client_hints/browser/client_hints.cc   the Sec-CH-UA headers
  content/browser/renderer_host/render_process_host_impl.cc
                                                     navigator.userAgentData
                                                     and the renderer's own
                                                     requests

"Google Chrome" gets Chromium's version, as in Chrome. The User-Agent string is
Chrome's already. The switch --neph-chromium-brand keeps Chromium's own list.
Only .cc files change.
"""


class AnchorMissing(Exception):
    pass


def replace_once(text, old, new, what):
    if text.count(old) != 1:
        raise AnchorMissing('%s: %s (found %d times)' % (what, old.strip().splitlines()[0], text.count(old)))
    return text.replace(old, new, 1)


HINTS = 'components/client_hints/browser/client_hints.cc'
RENDERER = 'content/browser/renderer_host/render_process_host_impl.cc'
FILES = (HINTS, RENDERER)

# The same few lines in both files: a lambda in place, no new symbol.
ADD_BRAND = '''[](blink::UserAgentMetadata& metadata) {
    if (base::CommandLine::ForCurrentProcess()->HasSwitch("neph-chromium-brand")) {
      return;
    }
    for (blink::UserAgentBrandList* list :
         {&metadata.brand_version_list, &metadata.brand_full_version_list}) {
      bool chrome = false;
      std::string version;
      for (const blink::UserAgentBrandVersion& entry : *list) {
        chrome = chrome || entry.brand == "Google Chrome";
        if (entry.brand == "Chromium") {
          version = entry.version;
        }
      }
      if (!chrome && !version.empty()) {
        list->emplace_back("Google Chrome", version);
      }
    }
  }'''

EDITS = {
    HINTS: [(
        '''blink::UserAgentMetadata ClientHints::GetUserAgentMetadata() {
  return embedder_support::GetUserAgentMetadata();
}''',
        '''blink::UserAgentMetadata ClientHints::GetUserAgentMetadata() {
  // Neph (24.10.2026, Opus 5.5): Chrome's brand in the list, as Chrome sends
  // it; without it Google shows its "Switch to Chrome" promotion
  // (scripts/chromium-patches/chrome_brand_patch.py).
  blink::UserAgentMetadata metadata = embedder_support::GetUserAgentMetadata();
  (''' + ADD_BRAND + ''')(metadata);
  return metadata;
}''')],
    RENDERER: [(
        '''  GetRendererInterface()->InitializeRenderer(
      GetContentClient()->browser()->GetUserAgent(),
      GetContentClient()->browser()->GetUserAgentMetadata(),''',
        '''  // Neph (24.10.2026, Opus 5.5): Chrome's brand in the renderer's
  // user-agent metadata too (navigator.userAgentData, the renderer's own
  // requests; scripts/chromium-patches/chrome_brand_patch.py).
  blink::UserAgentMetadata neph_ua_metadata =
      GetContentClient()->browser()->GetUserAgentMetadata();
  (''' + ADD_BRAND + ''')(neph_ua_metadata);
  GetRendererInterface()->InitializeRenderer(
      GetContentClient()->browser()->GetUserAgent(),
      neph_ua_metadata,''')],
}


def build(path, text):
    """text: the committed file. Returns the patched file."""
    if 'chrome_brand_patch.py' in text:
        raise AnchorMissing(path + ': already patched (expected the committed text)')
    for old, new in EDITS[path]:
        text = replace_once(text, old, new, path)
    return text
