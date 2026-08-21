import os
import urllib.request

all_factions = {
    "sons-of-calydon": "IconCampSonsOfCalydon.webp",
    "pubsec": "IconCampN.E.P.S..webp",
    "cunning-hares": "IconCampGentleHouse.webp",
    "belobog": "IconCampBelobogIndustries.webp",
    "victoria-housekeeping": "IconCampVictoriaHousekeepingCo..webp",
    "section-6": "IconCampH.S.O-S6.webp",
    "obols-squad": "IconCampObols.webp",
    "angels-of-delusion": "IconCampAngelsOfDelusion.webp",
    "black-root": "IconCampBlackRoot.webp",
    "mocking-bird": "IconCampMockingBird.webp",
    "spook-shack": "IconCampSpookShack.webp",
    "stars-of-lyra": "IconCampStarsOfLyra.webp",
    "suibian": "IconCampSuibian.webp",
}

base_url = "https://static.nanoka.cc/assets/zzz/{}"
dest_dir = "/root/fairy/frontend/public/icons"

os.makedirs(dest_dir, exist_ok=True)

print("Starting download of all 13 faction icons...")
for key, filename in all_factions.items():
    url = base_url.format(filename)
    dest_path = os.path.join(dest_dir, f"IconFaction_{key}.webp")
    # url is built from a hardcoded https:// constant above, not user input.
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})  # noqa: S310
    try:
        print(f"Downloading {url} -> {dest_path}")
        with urllib.request.urlopen(req) as res, open(dest_path, "wb") as f:  # noqa: S310
            f.write(res.read())
        print(f"  [SUCCESS] Saved {dest_path}")
    except Exception as e:
        print(f"  [ERROR] Failed to download {url}: {e}")

print("Completed downloading all 13 faction icons!")
