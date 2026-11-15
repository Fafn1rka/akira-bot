"""Скачивает 3D-библиотеки локально, чтобы аватар работал без интернета."""
import tomllib
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent


def main():
    cfg = tomllib.loads((BASE / "config.toml").read_text(encoding="utf-8"))["avatar"]
    t, v = cfg["three_version"], cfg["vrm_version"]
    cdn = "https://cdn.jsdelivr.net/npm"
    files = {
        "three/build/three.module.js": f"{cdn}/three@{t}/build/three.module.js",
        "three/examples/jsm/loaders/GLTFLoader.js": f"{cdn}/three@{t}/examples/jsm/loaders/GLTFLoader.js",
        "three/examples/jsm/utils/BufferGeometryUtils.js": f"{cdn}/three@{t}/examples/jsm/utils/BufferGeometryUtils.js",
        "three-vrm/three-vrm.module.js": f"{cdn}/@pixiv/three-vrm@{v}/lib/three-vrm.module.js",
    }
    for rel, url in files.items():
        dest = BASE / "web" / "vendor" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"Скачиваю {rel} ...")
        urllib.request.urlretrieve(url, dest)
    print("Готово. Теперь аватар работает офлайн.")


if __name__ == "__main__":
    main()
