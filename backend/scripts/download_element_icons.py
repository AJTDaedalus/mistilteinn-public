import os
import urllib.request

elements = ["Physical", "Fire", "Ice", "Electric", "Ether", "Wind"]
base_url = "https://static.nanoka.cc/assets/zzz/Icon{}.webp"
dest_dir = "/root/fairy/frontend/public/icons"

os.makedirs(dest_dir, exist_ok=True)

print("Starting download of element icons...")
for elem in elements:
    url = base_url.format(elem)
    dest_path = os.path.join(dest_dir, f"IconElement{elem}.webp")
    # url is built from a hardcoded https:// constant above, not user input.
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})  # noqa: S310
    try:
        print(f"Downloading {url} -> {dest_path}")
        with urllib.request.urlopen(req) as res, open(dest_path, "wb") as f:  # noqa: S310
            f.write(res.read())
        print(f"  [SUCCESS] Saved {dest_path}")
    except Exception as e:
        print(f"  [ERROR] Failed to download {url}: {e}")

print("Completed download of element icons!")
