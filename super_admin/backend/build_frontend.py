"""Copy only public Super Admin assets to Vercel's CDN directory."""
from pathlib import Path
import shutil


def main():
    root = Path(__file__).resolve().parents[2]
    source = root / "super_admin/frontend"
    output = root / "public/admin/assets"
    output.mkdir(parents=True, exist_ok=True)
    for name in ("dashboard.js", "login.js", "style.css", "network.js", "three.module.min.js", "THREE-LICENSE.txt"):
        shutil.copyfile(source / name, output / name)
    # Authenticated HTML is served by FastAPI, never published as an unguarded CDN page.
    print("Super Admin public assets prepared; authenticated HTML stays behind FastAPI.")


if __name__ == "__main__":
    main()
