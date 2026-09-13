"""Verify GGUF architecture and quantization metadata without loading tensors."""

import struct
import sys


def metadata(path):
    """Read bounded GGUF metadata using the public GGUF v2/v3 binary format."""
    with open(path, "rb") as file:

        def read(fmt):
            size = struct.calcsize(fmt)
            data = file.read(size)
            if len(data) != size:
                raise ValueError("Truncated GGUF metadata")
            return struct.unpack(fmt, data)[0]

        def string():
            size = read("<Q")
            if size > 2**20:
                raise ValueError("Unreasonable GGUF metadata string")
            data = file.read(size)
            if len(data) != size:
                raise ValueError("Truncated GGUF string")
            return data.decode("utf-8")

        def value(kind, depth=0):
            formats = {
                0: "<B",
                1: "<b",
                2: "<H",
                3: "<h",
                4: "<I",
                5: "<i",
                6: "<f",
                7: "<?",
                10: "<Q",
                11: "<q",
                12: "<d",
            }
            if kind in formats:
                return read(formats[kind])
            if kind == 8:
                return string()
            if kind == 9 and depth < 2:
                subtype, count = read("<I"), read("<Q")
                if count > 2**22:
                    raise ValueError("Unreasonable GGUF array")
                for _ in range(count):
                    value(subtype, depth + 1)
                return None
            raise ValueError(f"Unsupported GGUF metadata type {kind}")

        if file.read(4) != b"GGUF" or read("<I") not in (2, 3):
            raise ValueError("Expected GGUF v2 or v3")
        read("<Q")  # Tensor count.
        count = read("<Q")
        if count > 2**16:
            raise ValueError("Unreasonable GGUF metadata count")
        result = {}
        for _ in range(count):
            key, kind = string(), read("<I")
            result[key] = value(kind)
        return result


def validate(path, architecture, file_type):
    """Require actual model architecture and GGML file type (15 = Q4_K_M)."""
    data = metadata(path)
    if data.get("general.architecture") != architecture or data.get("general.file_type") != int(file_type):
        raise ValueError(
            f"Expected architecture={architecture}, file_type={file_type}; received "
            f"{data.get('general.architecture')}, {data.get('general.file_type')}"
        )
    if architecture == "asr" and (
        "nemotron-3.5-asr-streaming-0.6b" not in data.get("general.name", "")
        or data.get("asr.head_type") != "rnnt"
        or not data.get("asr.rnnt.num_prompts")
    ):
        raise ValueError("Expected multilingual Nemotron 3.5 streaming ASR")
    if architecture == "gpt-oss" and data.get("gpt-oss.block_count") != 24:
        raise ValueError("Expected gpt-oss-20b (24 blocks)")


if __name__ == "__main__":
    try:
        validate(*sys.argv[1:])
    except (ValueError, OSError, TypeError) as exc:
        raise SystemExit(str(exc)) from exc
