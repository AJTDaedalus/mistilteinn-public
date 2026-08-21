import re
import urllib.request

url = "https://zzz.nanoka.cc/character"
# url is a hardcoded https:// constant above, not user input.
req = urllib.request.Request(  # noqa: S310
    url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
)

try:
    with urllib.request.urlopen(req) as response:  # noqa: S310
        html = response.read().decode("utf-8")
        print("HTML length:", len(html))
        # Find all images or static assets
        urls = re.findall(r'/[^"\']*\.(?:png|webp|svg|ico)', html)
        print("Unique asset URLs found:")
        for u in sorted(set(urls)):
            print(f"  - {u}")
except Exception as e:
    print("Error:", e)
