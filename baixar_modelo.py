from huggingface_hub import hf_hub_download

caminho = hf_hub_download(
    repo_id="TommyNgx/YOLOv10-Fire-and-Smoke-Detection",
    filename="best.pt",
    local_dir="modelos"
)
print("Baixado em:", caminho)
