from typing import List, Dict, Any


def _base_ffmpeg_cmd(ffmpeg_path: str, input_path: str) -> List[str]:
    """Generates the base FFmpeg command."""
    return [
        ffmpeg_path,
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        input_path,
    ]


def generate_swap_streams_ffmpeg_cmd(
    all_streams_info: List[Dict[str, Any]],
    swap_pairs: List[List[int]],
    ffmpeg_path: str,
    input_path: str,
    output_path: str,
) -> List[str]:
    """
    Generates an ffmpeg command to swap specified audio/subtitle stream pairs.
    """
    original_indices = [s["index"] for s in all_streams_info if "index" in s]
    output_map_indices = list(original_indices)

    for idx_A, idx_B in swap_pairs:
        try:
            pos_A = output_map_indices.index(idx_A)
            pos_B = output_map_indices.index(idx_B)
            output_map_indices[pos_A], output_map_indices[pos_B] = (
                output_map_indices[pos_B],
                output_map_indices[pos_A],
            )
        except ValueError:
            print(f"Warning: Stream index {idx_A} or {idx_B} not found. Skipping swap.")
            continue

    cmd = _base_ffmpeg_cmd(ffmpeg_path, input_path)

    for original_stream_idx in output_map_indices:
        cmd.extend(["-map", f"0:{original_stream_idx}"])

    cmd.extend(["-c", "copy", output_path])
    return cmd


def generate_reorder_streams_ffmpeg_cmd(
    all_streams_info: List[Dict[str, Any]],
    user_defined_order: List[int],
    ffmpeg_path: str,
    input_path: str,
    output_path: str,
) -> List[str]:
    """
    Generates an ffmpeg command to reorder streams based on a user-defined list.
    """
    final_map_order = []
    mapped_indices = set()

    # 1. Add video streams first
    video_streams = [
        s["index"] for s in all_streams_info if s.get("codec_type") == "video"
    ]
    for idx in video_streams:
        if idx not in mapped_indices:
            final_map_order.append(idx)
            mapped_indices.add(idx)

    # 2. Add user-defined streams
    for idx in user_defined_order:
        if (
            any(s["index"] == idx for s in all_streams_info)
            and idx not in mapped_indices
        ):
            final_map_order.append(idx)
            mapped_indices.add(idx)

    # 3. Add remaining streams
    for s in all_streams_info:
        if s["index"] not in mapped_indices:
            final_map_order.append(s["index"])

    cmd = _base_ffmpeg_cmd(ffmpeg_path, input_path)

    audio_output_counter = 0
    for idx in final_map_order:
        cmd.extend(["-map", f"0:{idx}"])
        stream_info = next((s for s in all_streams_info if s.get("index") == idx), None)
        if stream_info and stream_info.get("codec_type") == "audio":
            cmd.extend(
                [
                    f"-disposition:a:{audio_output_counter}",
                    "default" if audio_output_counter == 0 else "none",
                ]
            )
            audio_output_counter += 1

    cmd.extend(["-c", "copy", output_path])
    return cmd
