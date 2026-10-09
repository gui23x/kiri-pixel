# Kiri Pixel

Aplicativo desktop em Python para remover o fundo de imagens e converter imagens em ícone `.ico`, mantendo resolução e qualidade.

<img src="https://i.pinimg.com/originals/f0/aa/5c/f0aa5cd7d48a4e57015060353056edb0.png" />

## Funcionalidades

- Remoção de fundo com modelos `u2net`, `isnet-general-use` e `birefnet-general`.
- Refino de bordas opcional (alpha matting).
- Exportação em PNG sem perda de qualidade.
- Exportação em ICO com os tamanhos 16, 24, 32, 48, 64, 128 e 256.
- Pré-visualização com fundo quadriculado para áreas transparentes.
- Processamento em thread separada, sem travar a interface.

## Requisitos

- Python compatível com `rembg` e `PySide6`
- [uv](https://docs.astral.sh/uv/)

## Instalação

```
uv add PySide6 PySide6-Fluent-Widgets pillow "rembg[cpu]"
```

## Execução

```
uv run python src/main.py
```

Na primeira execução de cada modelo, o arquivo do modelo é baixado e mantido em cache em `~/.u2net`.

## Estrutura

```
.
├── pyproject.toml
├── README.md
└── src
    ├── main.py
    └── assets
        └── icon.ico
```

## Uso

1. Clique em **Abrir imagem** e selecione um arquivo PNG, JPG, WEBP, BMP ou TIFF.
2. Opcional: escolha o modelo, ative **Refinar bordas** e clique em **Remover fundo**.
3. Clique em **Salvar PNG** ou **Salvar ICO**.

Os botões de salvar usam a imagem atual: o resultado sem fundo, caso a remoção tenha sido feita, ou a imagem original.

## Como funciona

### Remoção de fundo

`remove_background` executa o `rembg` na imagem original e retorna uma imagem RGBA na mesma resolução. A sessão do modelo é criada uma única vez por modelo e reutilizada.

### Conversão para ICO

`prepare_icon_source` executa quatro etapas:

1. Recorta a imagem nos limites do conteúdo visível, ignorando pixels quase transparentes.
2. Adiciona margem de 3% do maior lado.
3. Centraliza o conteúdo em um quadro quadrado transparente, sem distorção.
4. Redimensiona para 256x256 com LANCZOS.

`save_ico` grava o arquivo com todos os tamanhos de `ICO_SIZES`.

### Ícone e identificação na barra de tarefas

O ícone é carregado de `src/assets/icon.ico` e aplicado ao aplicativo e à janela. No Windows, `register_taskbar_identity` define um `AppUserModelID` único antes da criação do `QApplication`, o que impede o agrupamento com outros programas Python e mantém o ícone próprio na barra de tarefas.

Ao renomear o projeto, altere `APP_USER_MODEL_ID` em `src/main.py`.

## Configuração

As constantes ficam no topo de `src/main.py`:

| Constante | Função |
| --- | --- |
| `ICON_PATH` | Caminho do ícone do programa |
| `APP_USER_MODEL_ID` | Identificador único na barra de tarefas |
| `BACKGROUND_MODELS` | Modelos disponíveis para remoção de fundo |
| `ICO_SIZES` | Tamanhos gravados no arquivo ICO |
| `ICO_SIDE` | Lado da imagem base do ícone |
| `ICO_MARGIN_RATIO` | Margem do ícone em relação ao conteúdo |
| `ALPHA_CONTENT_THRESHOLD` | Limite de transparência para detectar conteúdo |

## Limitações

- O formato ICO aceita no máximo 256x256.
- Se `src/assets/icon.ico` não existir, o aplicativo inicia sem ícone e registra um aviso no log.