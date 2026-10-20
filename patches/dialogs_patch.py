"""The "dialogs" patch of apply.py: Chrome's own dialogs, bubbles and controls
in the form and the colours of Neph's menus (15.10.2026, Opus 5.5).

The publisher saw two of Chrome's dialogs in Neph - "Save password?" and the
passkey dialog - in Chrome's own Material look: rounded corners, pill buttons,
blue tonal surfaces, an illustration on top. They are to match Neph's other
menus, not to be two new designs. The shell's rule (ui/styles.css) is one
declaration: every radius is a chamfer (corner-shape:bevel), surfaces are
neutral grey, text is ink, the one hue is the accent. So:

1. Form. Where Chrome's views draw a rounded rectangle, they draw the same
   rectangle with its corners cut straight at 45 degrees by the radius:
   gfx::Canvas::DrawRoundRect (borders, ink drops, toggles), the bubble's
   outline, stroke, shadow and background (bubble_border.cc), the clip of a
   bubble's client view and its window mask (bubble_frame_view.cc), rounded
   backgrounds (background.cc) and painters (painter.cc, the Material
   buttons), and the paths of focus rings (highlight_path_generator.cc).
   Corner radii that the compositor applies to layers stay round; they sit
   inside the cut.
2. Sizes. The radius tables (ui/views/layout/layout_provider.cc) take Neph's
   four bevels: 3 px for controls and fields (bev-1), 6 px for buttons, which
   were pills (bev-2, Neph's primary button), 10 px for dialogs and menus
   (bev-3), 14 px for anything larger (bev-4).
3. Colours. A last colour mixer (chrome_color_mixers.cc) sets the dialog and
   bubble surfaces, text, buttons, fields, separators, focus ring and links to
   Neph's tokens for the light and the dark theme, with the accent the shell
   sends as the user colour (SetChromeColorScheme): the prominent button, the
   focus ring and links carry it, as in the shell.
4. No illustrations: the password bubbles' header image and the passkey
   dialog's illustration stay away, as Neph's menus have none. The switch
   --neph-illustrations brings them back.

Only .cc files change, no header: an incremental core build compiles ten
files and links.
"""


class AnchorMissing(Exception):
    pass


def replace_once(text, old, new, what):
    if text.count(old) != 1:
        raise AnchorMissing('%s: %s (found %d times)' % (what, old.strip().splitlines()[0], text.count(old)))
    return text.replace(old, new, 1)


MARK = 'Neph (15.10.2026): every radius is a chamfer'

# The chamfer, defined once per file that draws one (an anonymous namespace at
# file scope; no header, so nothing else recompiles).
BEVEL = '''// Neph (15.10.2026): every radius is a chamfer, as corner-shape:bevel in the
// shell (ui/styles.css): Chrome's dialogs, bubbles and controls get the cut
// corners of Neph's own menus (scripts/chromium-patches/dialogs_patch.py).
#include <algorithm>

#include "third_party/skia/include/core/SkPathBuilder.h"
#include "third_party/skia/include/core/SkRRect.h"

namespace {

[[maybe_unused]] SkPath NephBevel(const SkRect& r,
                                  SkScalar ul,
                                  SkScalar ur,
                                  SkScalar lr,
                                  SkScalar ll) {
  const SkScalar half = std::min(r.width(), r.height()) / 2;
  ul = std::max<SkScalar>(0, std::min(ul, half));
  ur = std::max<SkScalar>(0, std::min(ur, half));
  lr = std::max<SkScalar>(0, std::min(lr, half));
  ll = std::max<SkScalar>(0, std::min(ll, half));
  SkPathBuilder path;
  path.moveTo(r.fLeft + ul, r.fTop);
  path.lineTo(r.fRight - ur, r.fTop);
  path.lineTo(r.fRight, r.fTop + ur);
  path.lineTo(r.fRight, r.fBottom - lr);
  path.lineTo(r.fRight - lr, r.fBottom);
  path.lineTo(r.fLeft + ll, r.fBottom);
  path.lineTo(r.fLeft, r.fBottom - ll);
  path.lineTo(r.fLeft, r.fTop + ul);
  path.close();
  return path.detach();
}

[[maybe_unused]] SkPath NephBevel(const SkRRect& rr) {
  return NephBevel(rr.rect(), rr.radii(SkRRect::kUpperLeft_Corner).x(),
                   rr.radii(SkRRect::kUpperRight_Corner).x(),
                   rr.radii(SkRRect::kLowerRight_Corner).x(),
                   rr.radii(SkRRect::kLowerLeft_Corner).x());
}

}  // namespace

'''

CANVAS = 'ui/gfx/canvas.cc'
BORDER = 'ui/views/bubble/bubble_border.cc'
FRAME = 'ui/views/bubble/bubble_frame_view.cc'
BACKGROUND = 'ui/views/background.cc'
PAINTER = 'ui/views/painter.cc'
HIGHLIGHT = 'ui/views/controls/highlight_path_generator.cc'
LAYOUT = 'ui/views/layout/layout_provider.cc'
COLORS = 'chrome/browser/ui/color/chrome_color_mixers.cc'
PASSWORDS = 'chrome/browser/ui/views/passwords/password_bubble_view_base.cc'
WEBAUTHN = 'chrome/browser/ui/views/webauthn/authenticator_request_sheet_view.cc'
FILES = (CANVAS, BORDER, FRAME, BACKGROUND, PAINTER, HIGHLIGHT, LAYOUT, COLORS, PASSWORDS, WEBAUTHN)

# (file, anchor before which BEVEL goes)
BEVEL_AT = {
    CANVAS: '\nnamespace gfx {\n',
    BORDER: '\nnamespace views {\n',
    FRAME: '\nnamespace views {\n',
    BACKGROUND: '\nnamespace views {\n',
    PAINTER: '\nnamespace views {\n',
    HIGHLIGHT: '\nnamespace views {\n',
}

EDITS = {
    CANVAS: [(
        '''void Canvas::DrawRoundRect(const RectF& rect,
                           float radius,
                           const cc::PaintFlags& flags) {
  canvas_->drawRoundRect(RectFToSkRect(rect), SkFloatToScalar(radius),
                         SkFloatToScalar(radius), flags);
}''',
        '''void Canvas::DrawRoundRect(const RectF& rect,
                           float radius,
                           const cc::PaintFlags& flags) {
  // Neph: a chamfer where Chrome rounds (dialogs_patch.py).
  if (radius > 0) {
    const SkScalar cut = SkFloatToScalar(radius);
    canvas_->drawPath(NephBevel(RectFToSkRect(rect), cut, cut, cut, cut), flags);
    return;
  }
  canvas_->drawRoundRect(RectFToSkRect(rect), SkFloatToScalar(radius),
                         SkFloatToScalar(radius), flags);
}''')],
    BORDER: [(
        '''  gfx::ScopedCanvas scoped(canvas);
  SkRRect r_rect = GetClientRect(view);
  canvas->sk_canvas()->clipRRect(r_rect, SkClipOp::kDifference,
                                 true /*doAntiAlias*/);
  DrawBorderAndShadowImpl(r_rect, &cc::PaintCanvas::drawRRect, canvas,
                          view.GetColorProvider(), ShouldDrawStroke(),
                          md_shadow_elevation_, shadow_);
''',
        '''  gfx::ScopedCanvas scoped(canvas);
  SkRRect r_rect = GetClientRect(view);
  // Neph: outline, stroke and shadow follow the chamfer (dialogs_patch.py).
  canvas->sk_canvas()->clipPath(NephBevel(r_rect), SkClipOp::kDifference,
                                true /*doAntiAlias*/);
  if (ShouldDrawStroke()) {
    const SkScalar one_pixel = SkFloatToScalar(1.0f / canvas->image_scale());
    r_rect.outset(one_pixel, one_pixel);
  }
  canvas->sk_canvas()->drawPath(
      NephBevel(r_rect),
      GetBorderAndShadowFlags(view.GetColorProvider(), md_shadow_elevation_,
                              shadow_));
'''), (
        '''  canvas->sk_canvas()->clipRRect(GetClientRect(view), SkClipOp::kDifference,
                                 true /*doAntiAlias*/);
  canvas->sk_canvas()->drawColor(SkColors::kTransparent, SkBlendMode::kSrc);''',
        '''  canvas->sk_canvas()->clipPath(NephBevel(GetClientRect(view)),
                                SkClipOp::kDifference, true /*doAntiAlias*/);
  canvas->sk_canvas()->drawColor(SkColors::kTransparent, SkBlendMode::kSrc);'''), (
        '''  canvas->sk_canvas()->drawRRect(
      SkRRect(gfx::RRectF(bounds, border_->rounded_corners())), flags);''',
        '''  canvas->sk_canvas()->drawPath(
      NephBevel(SkRRect(gfx::RRectF(bounds, border_->rounded_corners()))),
      flags);''')],
    FRAME: [(
        '''  *path = SkPath::RRect(SkRRect::MakeRectRadii(
      SkRect::MakeIWH(size.width(), size.height()), radii));''',
        '''  *path = NephBevel(SkRRect::MakeRectRadii(
      SkRect::MakeIWH(size.width(), size.height()), radii));'''), (
        '''    *window_mask = SkPath::RRect(SkRRect::MakeRectRadii(rect, radii));''',
        '''    *window_mask = NephBevel(SkRRect::MakeRectRadii(rect, radii));''')],
    BACKGROUND: [(
        '''    const SkPath path =
        SkPath::RRect(SkRRect::MakeRectRadii(gfx::RectToSkRect(rect), radii));''',
        '''    const SkPath path =
        NephBevel(SkRRect::MakeRectRadii(gfx::RectToSkRect(rect), radii));''')],
    PAINTER: [(
        '''  const SkPath fill_path = SkPath::RRect(SkRRect::MakeRectRadii(
      gfx::RectFToSkRect(fill_rect), scaled_radii.data()));''',
        '''  const SkPath fill_path = NephBevel(SkRRect::MakeRectRadii(
      gfx::RectFToSkRect(fill_rect), scaled_radii.data()));'''), (
        '''    const SkPath stroke_path = SkPath::RRect(SkRRect::MakeRectRadii(
        gfx::RectFToSkRect(stroke_rect), stroke_radii.data()));''',
        '''    const SkPath stroke_path = NephBevel(SkRRect::MakeRectRadii(
        gfx::RectFToSkRect(stroke_rect), stroke_radii.data()));''')],
    HIGHLIGHT: [(
        '''  return SkPath::RRect(SkRRect{*round_rect});''',
        '''  return NephBevel(SkRRect{*round_rect});  // Neph: a chamfered focus ring''')],
    LAYOUT: [(
        '''    case Emphasis::kLow:
    case Emphasis::kMedium:
      return 4;
    case Emphasis::kHigh:
      return 8;''',
        '''    // Neph: the shell's bevels, 3 px on controls, 6 px above (dialogs_patch.py).
    case Emphasis::kLow:
    case Emphasis::kMedium:
      return 3;
    case Emphasis::kHigh:
      return 6;'''), (
        '''    case ShapeSysTokens::kXSmall:
      return 4;
    case ShapeSysTokens::kSmall:
      return 8;
    case ShapeSysTokens::kMediumSmall:
      return 12;
    case ShapeSysTokens::kMedium:
      return 16;
    case ShapeSysTokens::kLarge:
      return 24;
    case ShapeSysTokens::kFull:
      return std::min(size.width(), size.height()) / 2;''',
        '''    // Neph: the shell's four bevels (ui/styles.css --bev-1..4): fields and
    // small controls 3 px, buttons 6 px instead of pills (the primary button),
    // dialogs and menus 10 px, anything larger 14 px (dialogs_patch.py).
    case ShapeSysTokens::kXSmall:
      return 3;
    case ShapeSysTokens::kSmall:
      return 3;
    case ShapeSysTokens::kMediumSmall:
      return 10;
    case ShapeSysTokens::kMedium:
      return 14;
    case ShapeSysTokens::kLarge:
      return 14;
    case ShapeSysTokens::kFull:
      return std::min({6, size.width() / 2, size.height() / 2});''')],
    COLORS: [(
        '''#include "ui/color/color_provider_utils.h"
''',
        '''#include "ui/color/color_provider_utils.h"

#include <algorithm>
#include <cmath>

#include "third_party/skia/include/core/SkColor.h"
#include "ui/color/color_id.h"
#include "ui/color/color_mixer.h"
#include "ui/color/color_provider.h"
#include "ui/color/color_provider_key.h"
#include "ui/color/color_recipe.h"
#include "ui/color/color_transform.h"
#include "ui/gfx/color_utils.h"
'''), (
        '''void AddChromeColorMixers(ui::ColorProvider* provider,
                          const ui::ColorProviderKey& key) {''',
        '''namespace {

// Neph (15.10.2026): Chrome's own dialogs, bubbles and menus in the colours of
// the shell (ui/styles.css, dialogs_patch.py): neutral grey surfaces, ink for
// text, the accent - the shell's, sent as the user colour - for the prominent
// button, the focus ring and links. The accent's text and on-colour variants
// are derived in OKLCH, as the shell derives them.
struct NephLch {
  float l, c, h;
};

float NephLinear(float v) {
  return v <= 0.04045f ? v / 12.92f : std::pow((v + 0.055f) / 1.055f, 2.4f);
}

float NephEncode(float v) {
  v = std::clamp(v, 0.0f, 1.0f);
  return v <= 0.0031308f ? v * 12.92f : 1.055f * std::pow(v, 1 / 2.4f) - 0.055f;
}

NephLch NephToLch(SkColor color) {
  const float r = NephLinear(SkColorGetR(color) / 255.0f);
  const float g = NephLinear(SkColorGetG(color) / 255.0f);
  const float b = NephLinear(SkColorGetB(color) / 255.0f);
  const float l = std::cbrt(0.4122214708f * r + 0.5363325363f * g + 0.0514459929f * b);
  const float m = std::cbrt(0.2119034982f * r + 0.6806995451f * g + 0.1073969566f * b);
  const float s = std::cbrt(0.0883024619f * r + 0.2817188376f * g + 0.6299787005f * b);
  const float lightness = 0.2104542553f * l + 0.7936177850f * m - 0.0040720468f * s;
  const float a = 1.9779984951f * l - 2.4285922050f * m + 0.4505937099f * s;
  const float bb = 0.0259040371f * l + 0.7827717662f * m - 0.8086757660f * s;
  return {lightness, std::hypot(a, bb), std::atan2(bb, a)};
}

SkColor NephFromLch(float lightness, float chroma, float hue) {
  const float a = chroma * std::cos(hue);
  const float b = chroma * std::sin(hue);
  const float l = std::pow(lightness + 0.3963377774f * a + 0.2158037573f * b, 3.0f);
  const float m = std::pow(lightness - 0.1055613458f * a - 0.0638541728f * b, 3.0f);
  const float s = std::pow(lightness - 0.0894841775f * a - 1.2914855480f * b, 3.0f);
  const float r = 4.0767416621f * l - 3.3077115913f * m + 0.2309699292f * s;
  const float g = -1.2684380046f * l + 2.6097574011f * m - 0.3413193965f * s;
  const float bl = -0.0041960863f * l - 0.7034186147f * m + 1.7076147010f * s;
  return SkColorSetRGB(static_cast<U8CPU>(std::lround(NephEncode(r) * 255)),
                       static_cast<U8CPU>(std::lround(NephEncode(g) * 255)),
                       static_cast<U8CPU>(std::lround(NephEncode(bl) * 255)));
}

void AddNephColorMixer(ui::ColorProvider* provider,
                       const ui::ColorProviderKey& key) {
  const bool dark = key.color_mode == ui::ColorProviderKey::ColorMode::kDark;
  // The shell's tokens, oklch converted to sRGB (dark / light).
  const SkColor surface = dark ? SkColorSetRGB(0x0e, 0x0f, 0x11) : SkColorSetRGB(0xde, 0xdf, 0xe0);  // --s-2
  const SkColor sunk = dark ? SkColorSetRGB(0x00, 0x00, 0x01) : SkColorSetRGB(0xb4, 0xb6, 0xb8);     // --s-sunk
  const SkColor ink1 = dark ? SkColorSetRGB(0xf3, 0xf4, 0xf6) : SkColorSetRGB(0x14, 0x16, 0x19);
  const SkColor ink2 = dark ? SkColorSetRGB(0xbf, 0xc0, 0xc2) : SkColorSetRGB(0x37, 0x39, 0x3c);
  const SkColor ink3 = dark ? SkColorSetRGB(0x94, 0x96, 0x98) : SkColorSetRGB(0x45, 0x46, 0x49);
  const SkColor ink4 = dark ? SkColorSetRGB(0x67, 0x69, 0x6b) : SkColorSetRGB(0x7a, 0x7c, 0x7f);
  const SkColor edge_ctl = dark ? SkColorSetRGB(0x73, 0x75, 0x77) : SkColorSetRGB(0x59, 0x5b, 0x5d);
  const SkColor error = dark ? SkColorSetRGB(0xed, 0x75, 0x6e) : SkColorSetRGB(0x91, 0x07, 0x0f);
  // --edge-2: ink at 16 % (dark) or 22 % (light) over the surface.
  const SkColor edge2 = color_utils::AlphaBlend(ink1, surface, dark ? 0.16f : 0.22f);
  // --state-hover: the surface mixed with ink.
  const SkColor hover = color_utils::AlphaBlend(ink1, surface, dark ? 0.16f : 0.14f);
  const NephLch accent_lch = NephToLch(
      key.user_color.value_or(dark ? SkColorSetRGB(0xa9, 0xc1, 0xd9) : SkColorSetRGB(0x3f, 0x66, 0x86)));
  const SkColor accent = NephFromLch(dark ? 0.780f : 0.500f, accent_lch.c, accent_lch.h);
  const SkColor accent_text = NephFromLch(dark ? 0.840f : 0.420f, accent_lch.c, accent_lch.h);
  const SkColor accent_on = NephFromLch(dark ? 0.185f : 0.985f, dark ? 0.020f : 0.010f, accent_lch.h);

  ui::ColorMixer& mixer = provider->AddMixer();
  // Surfaces: the flyout's --s-2, its border --edge-2.
  for (ui::ColorId id : {ui::kColorBubbleBackground, ui::kColorDialogBackground,
                         ui::kColorBubbleFooterBackground, ui::kColorMenuBackground,
                         ui::kColorSysSurface, ui::kColorSysSurface1, ui::kColorSysSurface2,
                         ui::kColorSysSurface3, ui::kColorSysSurface4, ui::kColorSysSurface5}) {
    mixer[id] = {surface};
  }
  for (ui::ColorId id : {ui::kColorBubbleBorder, ui::kColorBubbleFooterBorder, ui::kColorSeparator,
                         ui::kColorMenuSeparator, ui::kColorMenuBorder, ui::kColorSysDivider}) {
    mixer[id] = {edge2};
  }
  // Text and icons.
  for (ui::ColorId id : {ui::kColorDialogForeground, ui::kColorLabelForeground,
                         ui::kColorMenuItemForeground, ui::kColorSysOnSurface,
                         ui::kColorButtonForeground, ui::kColorButtonForegroundTonal,
                         ui::kColorSysOnTonalContainer, ui::kColorTextfieldForeground}) {
    mixer[id] = {ink1};
  }
  for (ui::ColorId id : {ui::kColorLabelForegroundSecondary, ui::kColorSysOnSurfaceSecondary, ui::kColorIcon}) {
    mixer[id] = {ink2};
  }
  for (ui::ColorId id : {ui::kColorSysOnSurfaceSubtle, ui::kColorIconSecondary,
                         ui::kColorTextfieldForegroundPlaceholder}) {
    mixer[id] = {ink3};
  }
  for (ui::ColorId id : {ui::kColorLabelForegroundDisabled, ui::kColorButtonForegroundDisabled}) {
    mixer[id] = {ink4};
  }
  // Buttons: the prominent one in the accent (.primary-button), the others
  // sunk with a control edge (.chip), as the shell's dialogs have them.
  for (ui::ColorId id : {ui::kColorButtonBackgroundProminent, ui::kColorButtonBackgroundProminentFocused,
                         ui::kColorSysPrimary}) {
    mixer[id] = {accent};
  }
  mixer[ui::kColorButtonBackgroundProminentDisabled] = {SkColorSetA(accent, 0x5c)};
  for (ui::ColorId id : {ui::kColorButtonForegroundProminent, ui::kColorSysOnPrimary}) {
    mixer[id] = {accent_on};
  }
  for (ui::ColorId id : {ui::kColorButtonBackground, ui::kColorButtonBackgroundTonal,
                         ui::kColorButtonBackgroundTonalFocused, ui::kColorSysTonalContainer,
                         ui::kColorTextfieldBackground}) {
    mixer[id] = {sunk};
  }
  mixer[ui::kColorButtonBackgroundTonalDisabled] = {SkColorSetA(sunk, 0x5c)};
  for (ui::ColorId id : {ui::kColorButtonBorder, ui::kColorTextfieldOutline, ui::kColorSysNeutralOutline,
                         ui::kColorSysTonalOutline}) {
    mixer[id] = {edge_ctl};
  }
  mixer[ui::kColorButtonBorderDisabled] = {SkColorSetA(edge_ctl, 0x5c)};
  mixer[ui::kColorTextfieldSelectionBackground] = {color_utils::AlphaBlend(accent, surface, 0.35f)};
  mixer[ui::kColorMenuItemBackgroundSelected] = {hover};
  // The one hue: focus, links.
  for (ui::ColorId id : {ui::kColorFocusableBorderFocused, ui::kColorSysStateFocusRing,
                         ui::kColorLinkForeground, ui::kColorLinkForegroundPressed}) {
    mixer[id] = {accent_text};
  }
  mixer[ui::kColorTextfieldOutlineInvalid] = {error};
}

}  // namespace

void AddChromeColorMixers(ui::ColorProvider* provider,
                          const ui::ColorProviderKey& key) {'''), (
        '''  if (key.app_controller) {
    key.app_controller->AddColorMixers(provider, key);
  }
}''',
        '''  if (key.app_controller) {
    key.app_controller->AddColorMixers(provider, key);
  }

  // Neph: last, so Neph's colours win (dialogs_patch.py).
  AddNephColorMixer(provider, key);
}''')],
    PASSWORDS: [(
        '''void PasswordBubbleViewBase::SetBubbleHeader(int light_image_id,
                                             int dark_image_id) {
''',
        '''void PasswordBubbleViewBase::SetBubbleHeader(int light_image_id,
                                             int dark_image_id) {
  // Neph: no illustration, as Neph's menus have none (dialogs_patch.py).
  if (!base::CommandLine::ForCurrentProcess()->HasSwitch("neph-illustrations")) {
    return;
  }
'''), (
        '''void PasswordBubbleViewBase::SetBubbleHeaderLottie(int lottie_image_id) {
''',
        '''void PasswordBubbleViewBase::SetBubbleHeaderLottie(int lottie_image_id) {
  // Neph: no illustration, as Neph's menus have none (dialogs_patch.py).
  if (!base::CommandLine::ForCurrentProcess()->HasSwitch("neph-illustrations")) {
    return;
  }
'''), (
        '''#include "ui/base/metadata/metadata_impl_macros.h"
''',
        '''#include "ui/base/metadata/metadata_impl_macros.h"

#include "base/command_line.h"  // Neph (dialogs_patch.py)
''')],
    WEBAUTHN: [(
        '''AuthenticatorRequestSheetView::CreateIllustrationWithOverlays() {
  constexpr int kImageHeight = 112;''',
        '''AuthenticatorRequestSheetView::CreateIllustrationWithOverlays() {
  // Neph: no illustration, as Neph's menus have none (dialogs_patch.py).
  if (!base::CommandLine::ForCurrentProcess()->HasSwitch("neph-illustrations")) {
    return std::make_unique<views::View>();
  }
  constexpr int kImageHeight = 112;'''), (
        '''#include "ui/views/view_class_properties.h"
namespace {''',
        '''#include "ui/views/view_class_properties.h"

#include "base/command_line.h"  // Neph (dialogs_patch.py)

namespace {''')],
}


def build(path, text):
    """text: the committed file. Returns the patched file."""
    if MARK in text or 'dialogs_patch.py' in text:
        raise AnchorMissing(path + ': already patched (expected the committed text)')
    if path in BEVEL_AT:
        text = replace_once(text, BEVEL_AT[path], '\n' + BEVEL.replace('Neph (15.10.2026): every radius is a chamfer', MARK) + BEVEL_AT[path].lstrip('\n'), path)
    for old, new in EDITS[path]:
        text = replace_once(text, old, new, path)
    return text
