"""Demo manual: crea (una vez) el template de carousel, lo somete a aprobacion
de WhatsApp, y luego envia un carousel con los primeros productos scrapeados.

Uso:
  python -m scripts.send_carousel_demo create   # crea el template, imprime el ContentSid
  python -m scripts.send_carousel_demo approve <ContentSid>
  python -m scripts.send_carousel_demo status <ContentSid>   # consulta si ya lo aprobaron
  python -m scripts.send_carousel_demo send <ContentSid> whatsapp:+595XXXXXXXXX
"""

import sys

from app.templates.carousel import (
    check_approval_status,
    create_carousel_template,
    products_to_content_variables,
    send_carousel,
    submit_for_whatsapp_approval,
)
from worker.scraper import scrape_products


def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else ""

    if action == "create":
        content_sid = create_carousel_template("gandys_product_carousel", num_cards=3)
        print(f"ContentSid creado: {content_sid}")

    elif action == "approve":
        content_sid = sys.argv[2]
        result = submit_for_whatsapp_approval(content_sid, name="gandys_product_carousel")
        print(result)

    elif action == "status":
        content_sid = sys.argv[2]
        result = check_approval_status(content_sid)
        print(result)

    elif action == "send":
        content_sid = sys.argv[2]
        to_number = sys.argv[3]
        products = scrape_products()[:3]
        variables = products_to_content_variables("cliente", products)
        sid = send_carousel(to_number, content_sid, variables)
        print(f"Mensaje enviado: {sid}")

    else:
        print(__doc__)


if __name__ == "__main__":
    main()