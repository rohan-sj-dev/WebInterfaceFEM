import json
import fitz
from geometrys import BoundingBox
import math
from typing import Dict, Optional, List, Any


# ----------------------------------------------

def make_pdf_doc_searchable(
    pdf_doc: fitz.Document,
    textract_blocks: List[Dict[str, Any]],
    add_word_bbox: bool = False,
    show_selectable_char: bool = False,
    pdf_image_dpi: int = 200,
    verbose: bool = False,
) -> fitz.Document:
    """ """
    # save the pages as images (jpg) and buddle these images into a pdf document (pdf_doc_img)
    pdf_doc_img = fitz.open()
    for ppi, pdf_page in enumerate(pdf_doc.pages()):
        pdf_pix_map = pdf_page.get_pixmap(dpi=pdf_image_dpi, colorspace="RGB")
        pdf_page_img = pdf_doc_img.new_page(
            width=pdf_page.rect.width, height=pdf_page.rect.height
        )
        xref = pdf_page_img.insert_image(rect=pdf_page.rect, pixmap=pdf_pix_map)
    pdf_doc.close()

    # add the searchable character to the image PDF and bounding boxes if required by user
    print_step = 1000
    bbox_color = (220 / 255, 20 / 255, 60 / 255)  # red-ish color
    fontsize_initial = 15
    for blocki, block in enumerate(textract_blocks):
        if verbose:
            if blocki % print_step == 0:
                print(
                    (
                        f"processing blocks {blocki} to {blocki+print_step} out of {len(textract_blocks)} blocks"
                    )
                )
        if block["BlockType"] == "WORD":
            # get the page object
            page = 0  # zero-counting
            pdf_page = pdf_doc_img[page]
            # get the bbox object and scale it to the page pixel size
            bbox = BoundingBox.from_textract_bbox(block["Geometry"]["BoundingBox"])
            bbox.scale(pdf_page.rect.width, pdf_page.rect.height)

            # draw a bbox around each word
            if add_word_bbox:
                pdf_rect = fitz.Rect(bbox.left, bbox.top, bbox.right, bbox.bottom)
                pdf_page.draw_rect(
                    pdf_rect,
                    color=bbox_color,
                    fill=None,
                    width=0.7,
                    dashes=None,
                    overlay=True,
                    morph=None,
                )

            # add some text next to the bboxs
            fill_opacity = 1 if show_selectable_char else 0
            text = block["Text"]
            text_length = fitz.get_text_length(
                text, fontname="helv", fontsize=fontsize_initial
            )
            fontsize_optimal = int(
                math.floor((bbox.width / text_length) * fontsize_initial)
            )
            # Use insert_textbox for proper full-word highlighting
            rc = pdf_page.insert_textbox(
                fitz.Rect(bbox.left, bbox.top, bbox.right, bbox.bottom),
                text,
                fontname="helv",
                fontsize=fontsize_optimal,
                color=bbox_color,
                align=fitz.TEXT_ALIGN_LEFT,
                render_mode=3 if fill_opacity == 0 else 0,  # 3 = invisible
            )

    return pdf_doc_img

# ----------------------------------------------


doc = fitz.open("4340_spec.pdf")
data = json.load(open("response.json"))

textract_blocks = data["Blocks"]
print(f"no. of blocks {len(textract_blocks)}")

num_word_blocks = 0
for blk in textract_blocks:
    if blk["BlockType"] == "WORD":
        num_word_blocks += 1
print(f"number of WORD blocks {num_word_blocks}")

selectable_pdf_doc = make_pdf_doc_searchable(
    pdf_doc=doc,
    textract_blocks=textract_blocks,
    add_word_bbox=True,
    show_selectable_char=False,
    pdf_image_dpi=200,
    verbose=True,
)

selectable_pdf_doc.save("output.pdf")