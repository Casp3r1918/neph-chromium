"""The "platform_codecs" patch of apply.py: AAC through the system's decoder on
the Mac (19.10.2026, Fable 5.1; docs/video-vision.md, lane A).

Neph's cores carry no H.264 and no AAC decoder of their own
(ffmpeg_branding=Chromium). With proprietary_codecs=true Chromium nevertheless
treats both as supported and decodes H.264 in the GPU process through
VideoToolbox - a path that is complete in the tree. AAC is not: Chromium's
AudioToolboxAudioDecoder takes only xHE-AAC (and AC3/E-AC3), everything else
was ffmpeg's. This patch lets the system decoder take every AAC profile, so
that H.264/AAC pages (the embedded hosters of anime sites among them) play in
Neph's own tab, as they do in Firefox, which has relied on the platform's
licensed decoders for a decade. The protected view stays for copy protection.

1. media/filters/mac/audio_toolbox_audio_decoder.cc: CanUseAudioToolbox()
   accepts every AAC config; CreateDecoder() picks the AudioToolbox format
   from the AudioSpecificConfig (AAC-LC, HE-AAC with SBR, HE-AAC v2 with a
   mono core, xHE-AAC / USAC) instead of assuming USAC; the loudness and DRC
   properties that only USAC knows are set for USAC only.
2. media/mojo/services/gpu_mojo_media_client_mac.cc: the GPU process offers
   plain AAC (profile unknown = LC/HE) next to xHE-AAC, so the renderer sends
   it to the platform decoder.
3. media/ffmpeg/ffmpeg_common.cc: the file path. Without an ffmpeg AAC decoder
   avformat_find_stream_info() leaves sample_fmt empty, the AudioDecoderConfig
   is invalid and FFmpegDemuxer drops the audio stream without a word (the
   first build played the MP4's picture with 0 bytes of sound, 19.10.2026
   19:18). As Chromium does for AC3/E-AC3, AAC gets a nominal sample format;
   the platform decoder decides the real one.
4. media/filters/mac/audio_toolbox_audio_decoder.cc, the input: Chromium's MP4
   parser puts an ADTS header in front of every AAC frame it hands to MSE
   ("if possible", PrepareAACBuffer), because ffmpeg's decoder wanted one. The
   AudioConverter, set up with the raw AudioSpecificConfig, rejects such
   packets (the first build: MEDIA_ERR_DECODE after 938 bytes). The input
   callback now strips a leading ADTS header (7 or 9 bytes) whose frame
   length matches the packet.
5. media/BUILD.gn: the assertion "proprietary codecs and ffmpeg_branding set
   to Chromium are incompatible" is lifted. It guards nothing Neph relies on:
   the MSE parsers (mp4, H.264 Annex B conversion) are Chromium's own, the mov
   demuxer delivers framed packets without ffmpeg's h264/aac parsers, and the
   decoders are the system's. What stays absent: ADTS .aac files (no demuxer)
   and a software fallback for H.264 streams VideoToolbox refuses.

Windows (20.10.2026, W39): the same configuration, with Media Foundation in
place of AudioToolbox. H.264 is decoded by D3D11VideoDecoder (DXVA) in the
GPU process, a path that is complete in the tree; AAC was Media Foundation's
only for xHE-AAC on Windows 11 22H2:

6. media/filters/win/media_foundation_audio_decoder.cc: GetTypeInfo() returns
   the AAC decoder for every AAC profile (AAC-LC and HE-AAC since Windows 7;
   xHE-AAC keeps its 22H2 gate). The input type that mf_helpers.cc builds
   already carries the AudioSpecificConfig (HEAACWAVEINFO, raw payload).
7. The same file, PopulateInputSample(): for AAC a leading ADTS header whose
   frame length is the packet's own is skipped (point 4 on Windows; the
   decoder was told wPayloadType 0 = raw AAC).
8. media/mojo/services/gpu_mojo_media_client_win.cc: the GPU process offers
   plain AAC next to xHE-AAC (point 2 on Windows).

Five .cc files and one GN file, no header: an incremental core build compiles
them, links the media library and regenerates the projects. The Mac files sit
in the Windows tree as well and vice versa (same source, not compiled), so
the patch applies unchanged on both.
"""


class AnchorMissing(Exception):
    pass


def replace_once(text, old, new, what):
    n = text.count(old)
    if n != 1:
        raise AnchorMissing('%s: anchor found %d times' % (what, n))
    return text.replace(old, new)


DECODER = 'media/filters/mac/audio_toolbox_audio_decoder.cc'
CLIENT = 'media/mojo/services/gpu_mojo_media_client_mac.cc'
MEDIA_GN = 'media/BUILD.gn'
FFMPEG_COMMON = 'media/ffmpeg/ffmpeg_common.cc'
WIN_DECODER = 'media/filters/win/media_foundation_audio_decoder.cc'
WIN_CLIENT = 'media/mojo/services/gpu_mojo_media_client_win.cc'
FILES = (DECODER, CLIENT, FFMPEG_COMMON, MEDIA_GN, WIN_DECODER, WIN_CLIENT)


def build_decoder(text):
    text = replace_once(text,
        '#include "media/formats/mp4/es_descriptor.h"\n',
        '#include "media/formats/mp4/aac.h"\n'
        '#include "media/formats/mp4/es_descriptor.h"\n',
        'aac.h include')
    text = replace_once(text,
        '  // We use AudioToolbox for decoding xHE-AAC content and that\'s available on\n'
        '  // macOS 10.15 or higher.\n'
        '  return config.profile() == AudioCodecProfile::kXHE_AAC;\n'
        '}\n',
        '  // Neph (19.10.2026): every AAC profile - AAC-LC, HE-AAC v1/v2 and xHE-AAC -\n'
        '  // goes through AudioToolbox. The core carries no ffmpeg AAC decoder\n'
        '  // (ffmpeg_branding=Chromium); the system\'s decoder is the only one.\n'
        '  return config.codec() == AudioCodec::kAAC;\n'
        '}\n'
        '\n'
        '// Neph: the AudioToolbox format of an AAC AudioSpecificConfig (ISO 14496-3):\n'
        '// the audio object type (5 bits, 31 escapes to six more), then the sampling\n'
        '// frequency index (4 bits). Chromium\'s own parser knows the output rate with\n'
        '// an explicit SBR extension; above the base rate it is HE-AAC, with a mono\n'
        '// core HE-AAC v2 (whose decoder takes v1 as well).\n'
        'AudioFormatID AacFormatOf(const AudioDecoderConfig& config, MediaLog* media_log) {\n'
        '  const auto& asc = config.extra_data();\n'
        '  if (config.profile() == AudioCodecProfile::kXHE_AAC) {\n'
        '    return kAudioFormatMPEGD_USAC;\n'
        '  }\n'
        '  if (asc.size() < 2) {\n'
        '    return kAudioFormatMPEG4AAC;\n'
        '  }\n'
        '  unsigned object_type = asc[0] >> 3;\n'
        '  unsigned frequency_index = (asc[0] & 0x7) << 1 | asc[1] >> 7;\n'
        '  if (object_type == 31) {\n'
        '    object_type = 32 + (((asc[0] & 0x7) << 3) | (asc[1] >> 5));\n'
        '    frequency_index = (asc[1] >> 1) & 0xF;\n'
        '  }\n'
        '  if (object_type == mp4::AAC::kXHeAAcType) {\n'
        '    return kAudioFormatMPEGD_USAC;\n'
        '  }\n'
        '  static constexpr int kRates[] = {96000, 88200, 64000, 48000, 44100, 32000, 24000,\n'
        '                                   22050, 16000, 12000, 11025, 8000,  7350,  0,\n'
        '                                   0,     0};\n'
        '  const int base_rate = kRates[frequency_index & 0xF];\n'
        '  mp4::AAC parsed;\n'
        '  const bool sbr = object_type == 5 || object_type == 29 ||\n'
        '                   (base_rate > 0 && parsed.Parse(asc, media_log) &&\n'
        '                    parsed.GetOutputSamplesPerSecond(false) > base_rate);\n'
        '  if (!sbr) {\n'
        '    return kAudioFormatMPEG4AAC;\n'
        '  }\n'
        '  const unsigned channel_config = object_type >= 32 ? 0 : (asc[1] >> 3) & 0xF;\n'
        '  return object_type == 29 || channel_config == 1 ? kAudioFormatMPEG4AAC_HE_V2\n'
        '                                                   : kAudioFormatMPEG4AAC_HE;\n'
        '}\n',
        'CanUseAudioToolbox')
    text = replace_once(text,
        '  *num_packets = buffer_list->mNumberBuffers = 1;\n'
        '  buffer_list->mBuffers[0].mNumberChannels = 0;\n'
        '  buffer_list->mBuffers[0].mDataByteSize = input_data->buffer->size();\n'
        '\n'
        '  // No const version of this API unfortunately, so we need const_cast().\n'
        '  buffer_list->mBuffers[0].mData =\n'
        '      const_cast<uint8_t*>(base::span(*input_data->buffer).data());\n'
        '\n'
        '  if (packets)\n'
        '    *packets = &input_data->packet;\n',
        '  // Neph (19.10.2026): Chromium\'s MP4 parser (PrepareAACBuffer) puts an ADTS\n'
        '  // header in front of every AAC frame for MediaSource, for ffmpeg\'s sake.\n'
        '  // The AudioConverter is set up with the raw AudioSpecificConfig and does\n'
        '  // not take ADTS, so a leading header whose frame length is the packet\'s\n'
        '  // own is skipped: 7 bytes, 9 with a CRC (protection_absent == 0).\n'
        '  const auto data = base::span(*input_data->buffer);\n'
        '  size_t adts = 0;\n'
        '  if (data.size() >= 7 && data[0] == 0xFF && (data[1] & 0xF6) == 0xF0) {\n'
        '    const size_t frame_length = (static_cast<size_t>(data[3] & 0x03) << 11) |\n'
        '                                (static_cast<size_t>(data[4]) << 3) |\n'
        '                                (data[5] >> 5);\n'
        '    const size_t header = (data[1] & 0x01) ? 7 : 9;\n'
        '    if (frame_length == data.size() && data.size() > header)\n'
        '      adts = header;\n'
        '  }\n'
        '\n'
        '  *num_packets = buffer_list->mNumberBuffers = 1;\n'
        '  buffer_list->mBuffers[0].mNumberChannels = 0;\n'
        '  buffer_list->mBuffers[0].mDataByteSize = input_data->buffer->size() - adts;\n'
        '\n'
        '  // No const version of this API unfortunately, so we need const_cast().\n'
        '  buffer_list->mBuffers[0].mData =\n'
        '      const_cast<uint8_t*>(data.data() + adts);\n'
        '\n'
        '  if (packets) {\n'
        '    input_data->packet.mDataByteSize = input_data->buffer->size() - adts;\n'
        '    *packets = &input_data->packet;\n'
        '  }\n',
        'ProvideInputCallback')
    text = replace_once(text,
        '    case AudioCodec::kAAC: {\n'
        '      // Input is xHE-AAC / USAC.\n'
        '      CHECK_EQ(config.profile(), AudioCodecProfile::kXHE_AAC);\n'
        '      input_format.mFormatID = kAudioFormatMPEGD_USAC;\n'
        '      magic_cookie = mp4::ESDescriptor::CreateEsds(config.extra_data());\n',
        '    case AudioCodec::kAAC: {\n'
        '      // Neph (19.10.2026): AAC-LC, HE-AAC or xHE-AAC, from the config.\n'
        '      if (config.extra_data().empty()) {\n'
        '        MEDIA_LOG(ERROR, media_log_) << "AAC without an AudioSpecificConfig";\n'
        '        return false;\n'
        '      }\n'
        '      input_format.mFormatID = AacFormatOf(config, media_log_.get());\n'
        '      magic_cookie = mp4::ESDescriptor::CreateEsds(config.extra_data());\n',
        'CreateDecoder AAC case')
    text = replace_once(text,
        '    // macOS doesn\'t provide a default target loudness. Use the value\n'
        '    // recommended by Fraunhofer. AC3/E-AC3 doesn\'t support set this,\n'
        '    // so limit this to xHE-AAC only.\n'
        '    const Float32 kDefaultLoudness = -16.0;\n',
        '    // macOS doesn\'t provide a default target loudness. Use the value\n'
        '    // recommended by Fraunhofer. AC3/E-AC3 doesn\'t support set this,\n'
        '    // so limit this to xHE-AAC only (Neph: AAC-LC and HE-AAC neither).\n'
        '    if (input_format.mFormatID != kAudioFormatMPEGD_USAC) {\n'
        '      // Nothing more to set for the older profiles.\n'
        '    } else {\n'
        '    const Float32 kDefaultLoudness = -16.0;\n',
        'loudness')
    text = replace_once(text,
        '      OSSTATUS_MEDIA_LOG(ERROR, result, media_log_)\n'
        '          << "AudioConverterSetProperty() failed to set DRC effect type.";\n'
        '      return false;\n'
        '    }\n'
        '  }\n',
        '      OSSTATUS_MEDIA_LOG(ERROR, result, media_log_)\n'
        '          << "AudioConverterSetProperty() failed to set DRC effect type.";\n'
        '      return false;\n'
        '    }\n'
        '    }\n'
        '  }\n',
        'DRC block end')
    return text


def build_client(text):
    return replace_once(text,
        '    audio_configs.emplace_back(AudioCodec::kAAC, AudioCodecProfile::kXHE_AAC);\n',
        '    audio_configs.emplace_back(AudioCodec::kAAC, AudioCodecProfile::kXHE_AAC);\n'
        '    // Neph (19.10.2026): AAC-LC and HE-AAC through AudioToolbox as well.\n'
        '    audio_configs.emplace_back(AudioCodec::kAAC, AudioCodecProfile::kUnknown);\n',
        'supported audio configs')


def build_ffmpeg_common(text):
    return replace_once(text,
        '    default:\n'
        '      break;\n'
        '  }\n'
        '\n'
        '  base::TimeDelta seek_preroll;\n',
        '    // Neph (19.10.2026): AAC is demuxed here and decoded by the platform\n'
        '    // (AudioToolbox), so ffmpeg has no decoder to fill |sample_fmt| and the\n'
        '    // stream would be dropped as invalid. A nominal format, like AC3 above;\n'
        '    // the decoder outputs float planar whatever is written here.\n'
        '    case AudioCodec::kAAC:\n'
        '      if (sample_format == kUnknownSampleFormat)\n'
        '        sample_format = kSampleFormatF32;\n'
        '      break;\n'
        '\n'
        '    default:\n'
        '      break;\n'
        '  }\n'
        '\n'
        '  base::TimeDelta seek_preroll;\n',
        'ffmpeg_common AAC sample format')


def build_gn(text):
    return replace_once(text,
        'if (proprietary_codecs && media_use_ffmpeg) {\n'
        '  assert(\n'
        '      ffmpeg_branding != "Chromium",\n'
        '      "proprietary codecs and ffmpeg_branding set to Chromium are incompatible")\n'
        '}\n',
        '# Neph (19.10.2026): proprietary_codecs with ffmpeg_branding=Chromium is\n'
        '# Neph\'s own configuration - H.264 and AAC through the platform\'s decoders,\n'
        '# none of ffmpeg\'s (platform_codecs_patch.py). The assertion that forbade\n'
        '# the pair is lifted.\n',
        'media/BUILD.gn assertion')


def build_win_decoder(text):
    text = replace_once(text,
        '#if BUILDFLAG(USE_PROPRIETARY_CODECS)\n'
        '    case AudioCodec::kAAC:\n'
        '      if (config.profile() == AudioCodecProfile::kXHE_AAC &&\n'
        '          base::win::GetVersion() >= base::win::Version::WIN11_22H2) {\n'
        '        return MFT_REGISTER_TYPE_INFO{MFMediaType_Audio, MFAudioFormat_AAC};\n'
        '      }\n'
        '      [[fallthrough]];\n'
        '#endif\n',
        '#if BUILDFLAG(USE_PROPRIETARY_CODECS)\n'
        '    case AudioCodec::kAAC:\n'
        '      // Neph (20.10.2026): every AAC profile goes to Media Foundation\'s AAC\n'
        '      // decoder - AAC-LC and HE-AAC v1/v2 (Windows 7 and later), xHE-AAC\n'
        '      // from Windows 11 22H2. The core carries no ffmpeg AAC decoder\n'
        '      // (ffmpeg_branding=Chromium); the system\'s decoder is the only one.\n'
        '      if (config.profile() != AudioCodecProfile::kXHE_AAC ||\n'
        '          base::win::GetVersion() >= base::win::Version::WIN11_22H2) {\n'
        '        return MFT_REGISTER_TYPE_INFO{MFMediaType_Audio, MFAudioFormat_AAC};\n'
        '      }\n'
        '      [[fallthrough]];\n'
        '#endif\n',
        'GetTypeInfo AAC case')
    text = replace_once(text,
        'bool PopulateInputSample(IMFSample* sample, const DecoderBuffer& input) {\n',
        'bool PopulateInputSample(IMFSample* sample,\n'
        '                         const DecoderBuffer& input,\n'
        '                         bool strip_adts) {\n',
        'PopulateInputSample signature')
    text = replace_once(text,
        '  RETURN_ON_FAILURE(!current_length, "Input length is zero", false);\n'
        '  RETURN_ON_FAILURE(input.size() <= max_length, "Input length is too long",\n'
        '                    false);\n'
        '  destination.copy_prefix_from(input);\n'
        '\n'
        '  hr = buffer->SetCurrentLength(input.size());\n',
        '  // Neph (20.10.2026): Chromium\'s MP4 parser (PrepareAACBuffer) puts an ADTS\n'
        '  // header in front of every AAC frame it hands to MediaSource, for ffmpeg\'s\n'
        '  // sake. The decoder\'s input type announces raw AAC (wPayloadType 0), so a\n'
        '  // leading header whose frame length is the packet\'s own is skipped: 7\n'
        '  // bytes, 9 with a CRC (protection_absent == 0). The file path delivers\n'
        '  // raw frames and is left alone.\n'
        '  base::span<const uint8_t> payload = base::span(input);\n'
        '  if (strip_adts && payload.size() >= 7 && payload[0] == 0xFF &&\n'
        '      (payload[1] & 0xF6) == 0xF0) {\n'
        '    const size_t frame_length = (static_cast<size_t>(payload[3] & 0x03) << 11) |\n'
        '                                (static_cast<size_t>(payload[4]) << 3) |\n'
        '                                (payload[5] >> 5);\n'
        '    const size_t header = (payload[1] & 0x01) ? 7 : 9;\n'
        '    if (frame_length == payload.size() && payload.size() > header)\n'
        '      payload = payload.subspan(header);\n'
        '  }\n'
        '\n'
        '  RETURN_ON_FAILURE(!current_length, "Input length is zero", false);\n'
        '  RETURN_ON_FAILURE(payload.size() <= max_length, "Input length is too long",\n'
        '                    false);\n'
        '  destination.copy_prefix_from(payload);\n'
        '\n'
        '  hr = buffer->SetCurrentLength(payload.size());\n',
        'PopulateInputSample ADTS')
    text = replace_once(text,
        '  if (!PopulateInputSample(sample.Get(), *buffer)) {\n',
        '  if (!PopulateInputSample(sample.Get(), *buffer,\n'
        '                           config_.codec() == AudioCodec::kAAC)) {\n',
        'PopulateInputSample call')
    return text


def build_win_client(text):
    return replace_once(text,
        '    if (base::win::GetVersion() >= base::win::Version::WIN11_22H2 &&\n'
        '        InitializeMediaFoundation()) {\n'
        '      audio_configs.emplace_back(AudioCodec::kAAC, AudioCodecProfile::kXHE_AAC);\n'
        '    }\n',
        '    if (InitializeMediaFoundation()) {\n'
        '      // Neph (20.10.2026): AAC-LC and HE-AAC through Media Foundation as well\n'
        '      // (platform_codecs_patch.py); xHE-AAC stays a Windows 11 22H2 matter.\n'
        '      audio_configs.emplace_back(AudioCodec::kAAC, AudioCodecProfile::kUnknown);\n'
        '      if (base::win::GetVersion() >= base::win::Version::WIN11_22H2) {\n'
        '        audio_configs.emplace_back(AudioCodec::kAAC,\n'
        '                                   AudioCodecProfile::kXHE_AAC);\n'
        '      }\n'
        '    }\n',
        'supported audio configs (win)')


def build(path, text):
    if path == DECODER:
        return build_decoder(text)
    if path == CLIENT:
        return build_client(text)
    if path == FFMPEG_COMMON:
        return build_ffmpeg_common(text)
    if path == MEDIA_GN:
        return build_gn(text)
    if path == WIN_DECODER:
        return build_win_decoder(text)
    if path == WIN_CLIENT:
        return build_win_client(text)
    raise AnchorMissing('unknown file ' + path)
