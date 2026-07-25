"""Demo manual: crea (una vez) el template de carousel, lo somete a aprobacion
de WhatsApp, y luego envia un carousel con los primeros productos scrapeados.

Uso:
  python -m scripts.send_carousel_demo create   # crea el template, imprime el ContentSid
  python -m scripts.send_carousel_demo approve <ContentSid>
  python -m scripts.send_carousel_demo status <ContentSid>   # consulta si ya lo aprobaron
  python -m scripts.send_carousel_demo send <ContentSid> whatsapp:+595XXXXXXXXX
"""

import json
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
        all_products = scrape_products()
        # Igual que get_product_matches() en produccion: sin imagen, la
        # tarjeta no tiene sentido, y ademas Twilio rechaza el envio entero
        # si una variable de media queda vacia (error 21656).
        products_with_image = [p for p in all_products if p.get("image_url")]
        products = products_with_image[:3]
        if len(products) < 3:
            print(
                f"Solo se encontraron {len(products)} productos con imagen "
                "(se necesitan 3). Probá de nuevo o revisá el scraper."
            )
            return

        variables = products_to_content_variables("cliente", products)

        # DEBUG temporal: imprime exactamente que se le manda a Twilio, para
        # detectar a simple vista un valor vacio/raro sin adivinar. Sacar
        # despues de resolver el error 21656.
        print("--- content_variables a enviar ---")
        print(json.dumps(variables, indent=2, ensure_ascii=False))
        for key, value in variables.items():
            print(f"  {key!r}: len={len(value)} repr={value!r}")
        print("-----------------------------------")

        sid = send_carousel(to_number, content_sid, variables)
        print(f"Mensaje enviado: {sid}")

    else:
        print(__doc__)


if __name__ == "__main__":
    main()