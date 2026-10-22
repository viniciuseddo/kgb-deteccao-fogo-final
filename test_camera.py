import sys
import cv2

fonte = sys.argv[1] if len(sys.argv) > 1 else "0"
if fonte.isdigit():
    fonte = int(fonte)

cap = cv2.VideoCapture(fonte)
if not cap.isOpened():
    print("Nao abriu a fonte:", fonte)
    sys.exit(1)

print("Camera aberta. Aperte Q para sair.")
while True:
    ok, frame = cap.read()
    if not ok:
        print("Falhou ao ler frame")
        break
    cv2.imshow("teste", frame)
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()