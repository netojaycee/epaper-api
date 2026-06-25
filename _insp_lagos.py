import sys, zipfile, xml.etree.ElementTree as ET, re
sys.path.insert(0, r"C:\Users\Edeh JayCee\Desktop\idml-automation\fast-api")

path = r"C:\Users\Edeh JayCee\Desktop\idml-automation\assets\idml\LAGOS MON.idml"

with zipfile.ZipFile(path) as z:
    dm = z.read("designmap.xml").decode("utf-8", errors="ignore")
    root_dm = ET.fromstring(dm)
    story_list = root_dm.get("StoryList", "").split()
    doc_name = root_dm.get("Name", "")
    print(f"Doc: {doc_name}  |  Stories: {len(story_list)}")

    # Inspect first 25 stories for structure
    for sid in story_list[:30]:
        sf = f"Stories/Story_{sid}.xml"
        if sf not in z.namelist(): continue
        content = z.read(sf).decode("utf-8", errors="ignore")
        root2 = ET.fromstring(content)
        para_ranges = root2.findall(".//ParagraphStyleRange")
        if not para_ranges: continue

        items = []
        for pr in para_ranges[:2]:
            just = pr.get("Justification","")
            style = pr.get("AppliedParagraphStyle","").split("/")[-1]
            for cr in pr.findall(".//CharacterStyleRange")[:2]:
                fs = cr.get("FontStyle","")
                ps = cr.get("PointSize","?")
                for c in cr.findall("Content"):
                    if c.text and c.text.strip():
                        items.append(f"[{style}|{fs}|{ps}pt|{just}] {c.text[:60]}")
        
        # Check for "Continued from" / "Continues on" markers
        all_text = " ".join(c.text or "" for c in root2.findall(".//Content"))
        has_cont = bool(re.search(r'continu', all_text, re.I))
        
        if items:
            print(f"\nStory {sid} ({len(para_ranges)} paras) {'[CONTINUES]' if has_cont else ''}:")
            for it in items[:3]:
                print(f"  {it}")

    # Check spreads for image links
    print("\n=== Spreads ===")
    for sf in [f for f in z.namelist() if f.startswith("Spreads/")]:
        raw = z.read(sf).decode("utf-8", errors="ignore")
        links = re.findall(r'LinkResourceURI="([^"]+)"', raw)
        if links:
            print(f"{sf}: {len(links)} links")
            for l in links[:3]:
                print(f"  {l[:80]}")
