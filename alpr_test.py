from fast_alpr import ALPR

alpr = ALPR(
    detector_model="yolo-v9-t-384-license-plate-end2end",
    ocr_model="cct-xs-v2-global-model",
)

results = alpr.predict("car.jpg")

for result in results:

    if result.ocr:

        print(
            "Detected Plate:",
            result.ocr.text
        )