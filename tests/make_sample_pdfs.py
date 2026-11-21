from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet

S = getSampleStyleSheet()
DOCS = {
    "laptop_alpha.pdf": ("Alpha Book 14 - Product Sheet", [
        ["Price: The Alpha Book 14 costs Rs. 54,999 including GST.",
         "Processor: Intel Core i5 13th Gen with 16 GB RAM and 512 GB SSD.",
         "Display: 14-inch Full HD IPS, 300 nits."],
        ["Battery: 10 hours of mixed usage, 65W fast charger.",
         "Warranty: 1 year onsite warranty, extendable to 3 years for Rs. 4,000.",
         "Weight: 1.4 kg. Student discount of 5% available with college ID."]]),
    "laptop_beta.pdf": ("Beta Pro 15 - Product Sheet", [
        ["Price: The Beta Pro 15 costs Rs. 72,500 including GST.",
         "Processor: AMD Ryzen 7 7840HS with 16 GB RAM and 1 TB SSD.",
         "Display: 15.6-inch 2K 120Hz panel, 400 nits."],
        ["Battery: 8 hours of mixed usage, 100W USB-C charger.",
         "Warranty: 2 years carry-in warranty with accidental damage protection.",
         "Weight: 1.8 kg. Includes a dedicated RTX 4050 graphics card."]]),
    "laptop_gamma.pdf": ("Gamma Air 13 - Product Sheet", [
        ["Price: The Gamma Air 13 costs Rs. 46,990 including GST.",
         "Processor: Intel Core i3 13th Gen with 8 GB RAM and 256 GB SSD.",
         "Display: 13.3-inch Full HD, 250 nits."],
        ["Battery: 12 hours of mixed usage, 45W charger.",
         "Weight: 1.1 kg, the lightest in its class.",
         "Ideal for note-taking and online classes."]]),
}
for fname, (title, pages) in DOCS.items():
    story = [Paragraph(title, S["Title"])]
    for i, page in enumerate(pages):
        story += [Paragraph(t, S["BodyText"]) for t in page] + [Spacer(1, 12)]
        if i < len(pages) - 1:
            story.append(PageBreak())
    SimpleDocTemplate(f"sample_pdfs/{fname}", pagesize=A4).build(story)
print("done")
