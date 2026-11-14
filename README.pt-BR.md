# Palettier

> **Idioma:** [English](README.md) | **Português (PT-BR)**

Sincronizador dinâmico de temas e pacote de ícones **Material Design 3** para desktop Linux (GNOME), extraindo a paleta de cores diretamente do papel de parede ativo.

---

## 1. Visão Geral

O **Palettier** detecta o papel de parede ativo (via GSettings/GNOME, XML de slideshow ou arquivo local), extrai a cor de destaque dominante com quantização adaptativa e gera tokens tonais **Material Design 3 (CAM16 / HCT)** para sincronizar automaticamente:

- **Pacote de Ícones Dinâmico Material Design 3** (`Palettier-M3-A` / `Palettier-M3-B`):
  - Pastas (`places/`) e tipos de arquivo (`mimetypes/`) em SVG seguindo os tokens tonais M3.
  - Filtro tonal M3 aplicado aos ícones originais de **todos os aplicativos instalados** (`.desktop` de sistema, usuário, Flatpak, Snap e **AppImage**), preservando 100% da silhueta, transparência e geometria original.
- **Prompt do Terminal (`Starship`)** (`~/.config/starship.toml`).
- **Emulador de Terminal GNOME (`Ptyxis`)** (`palettier.palette` + atualização via GSettings).
- **Navegador Web `Firefox`** (`userChrome.css` e `user.js` em todos os perfis ativos, com suporte a abas horizontais e verticais).
- **Cor de Destaque Nativa do GNOME 47+** (`org.gnome.desktop.interface accent-color`).

> [!NOTE]
> **Sem dependências de extensões externas**: toda a extração de cores e o cálculo da paleta Material Design 3 são executados nativamente em Python pelo pacote [`palettier`](palettier/).

---

## 2. Arquitetura e Fluxo de Execução

```mermaid
flowchart TD
    A[GNOME Desktop: Troca de Papel de Parede] -->|GSettings picture-uri / picture-uri-dark| D[Palettier: palettier.sync]
    A2[Arquivo de Imagem Local] -->|Gio.FileMonitor / inotify| D

    subgraph D-Bus e Suspensão
        S1[systemd-logind: PrepareForSleep false] --> D
        S2[ScreenSaver: ActiveChanged false] --> D
        S3[Timer Monotônico: Salto > 5s] --> D
    end

    subgraph Extração e Motor Material Design 3
        D --> E1[Pillow / Quantização MedianCut ou SVG]
        E1 --> E2[Motor CAM16 / HCT: palettier.palette]
        E2 --> E3[Tokens M3, Accent e Superfícies Tinted]
    end

    E3 -->|1. starship.toml| F1[Starship Prompt]
    E3 -->|2. palettier.palette| F2[Ptyxis Terminal]
    E3 -->|3. userChrome.css + user.js| F3[Firefox]
    E3 -->|4. accent-color| F4[GNOME 47+ Native Accent]
    E3 -->|5. palettier.icons| F5[Ícones M3 Slots A/B]
```

---

## 3. Requisitos e Instalação

### Dependências

- **Python 3.10+**
- **Pillow (`PIL`)**: extração de cores do wallpaper e filtro tonal M3 em ícones raster (`.png`, `.webp`, `.jpg`, `.ico` e PNGs embutidos em SVG).
- **PyGObject (`python3-gi`)** *(recomendado para `--watch`)*: monitoramento em tempo real via GSettings, `Gio.FileMonitor` e sinais D-Bus de suspensão/desbloqueio.
  ```bash
  sudo apt install python3-gi gir1.2-gio-2.0
  ```
- **Ferramentas do ambiente** *(opcionais, conforme os apps que você utiliza)*: `gsettings` (GNOME), `starship`, `Ptyxis`, `Firefox`.

### Instalação Rápida

```bash
git clone https://github.com/PedroMachado1/Palettier.git
cd Palettier

# Instale o pacote e o comando CLI `palettier`
pip install .
# Ou em modo editável para desenvolvimento:
# pip install -e .

# Teste uma sincronização única
palettier

# Instale e habilite o serviço automático de sessão (systemd --user)
palettier --install-service
systemctl --user daemon-reload
systemctl --user enable --now palettier.service
```

> Também é possível executar diretamente sem instalar usando `python3 -m palettier`.
> `--install-service` gera automaticamente `~/.config/systemd/user/palettier.service` apontando para o interpretador Python atual e para o caminho real do projeto.

---

## 4. Detalhes dos Módulos e Integrações

### 4.1. Núcleo e Extração (`palettier/wallpaper.py` & `palettier/state.py`)

1. **Detecção do Papel de Parede (`get_current_wallpaper_path`)**:
   - Lê `org.gnome.desktop.interface color-scheme` e consulta `picture-uri-dark` ou `picture-uri` em `org.gnome.desktop.background`.
   - Converte URIs `file://`, decodifica caracteres especiais, resolve slideshows `.xml` do GNOME e possui fallbacks (`~/.config/background`, `~/.fehbg` e diretórios padrão de wallpapers).
2. **Extração e Matemática de Cores (`extract_wallpaper_colors`)**:
   - Redimensiona a imagem para processamento rápido e aplica quantização adaptativa de 24 cores (`MedianCut`).
   - Pontua cores candidatas equilibrando população, saturação e luminosidade:
     $$\text{Score} = \text{População}^{0.55} \times \text{Saturação}^{1.4} \times \text{FatorLuminosidade}$$
   - Calcula automaticamente o *tint intensity* (`0.08` a `0.14`) conforme a saturação média do wallpaper e também suporta papéis de parede vetoriais em `.svg`.
3. **Cache de Estado (`$XDG_RUNTIME_DIR/palettier.state`)**:
   - Evita reprocessamento redundante quando wallpaper (SHA-256), esquema de cores, URIs e modo de ícones não mudaram (a menos que `--force` seja usado).
   - Aguarda automaticamente o término de transações RPM/DNF ativas antes de avaliar o estado.

### 4.2. Pacote de Ícones Dinâmico Material Design 3 (`palettier/palette.py` & `palettier/icons.py`)

1. **Motor CAM16 / HCT (`palettier/palette.py`)**:
   - Implementação em Python puro de `SchemeTonalSpot` (Material Design 3), derivando tokens para **Dark** e **Light** (`primary`, `secondary`, `tertiary`, `error`, `surfaceContainer*`, `outlineVariant`) com contraste WCAG verificado.
   - Gera tabelas de consulta perceptuais (`build_icon_tint_luts`) para mapear ícones originais para a paleta do wallpaper mantendo luzes, sombras, brancos e contraste.
2. **Pastas, Mimetypes e Filtro Tonal em Todos os Apps (`palettier/icons.py`)**:
   - Cria os ícones M3 em `~/.local/share/icons/Palettier-M3-{A,B}/scalable/` para `places/` e `mimetypes/`.
   - Varre todos os `.desktop` instalados (sistema, usuário, Flatpak, Snap, **AppImage** e `XDG_DATA_DIRS`) e busca seus ícones em temas instalados, diretórios `pixmaps/` e ícones soltos em `~/.local/share/icons/` ou `~/.icons/`.
   - Aplica o filtro tonal M3 sobre `.svg`, `.svgz`, `.png`, `.webp`, `.jpg` e `.ico` sem alterar formato, contorno, transparência ou geometria original.
   - Constrói a cadeia `Inherits=` no `index.theme` priorizando temas locais existentes (`MoreWaita`, `Papirus-Dark`/`Papirus`, `Adwaita`, `hicolor`).
3. **Ponte Reversível para AppImages (`.desktop` com caminho absoluto)**:
   - Aplicativos AppImage costumam definir `Icon=/caminho/absoluto/...` no `.desktop` do usuário (`~/.local/share/applications/`), o que faz o GNOME ignorar o tema de ícones ativo.
   - O Palettier copia o ícone original para `hicolor`, registra o valor original em `~/.local/share/icons/.palettier_desktop_icons.json` e troca `Icon=` para um nome temável `palettier-app-*`.
   - Ao executar `palettier --uninstall`, todos os `.desktop` modificados são restaurados exatamente para o valor original.
4. **Modos de Ícones (`--icon-mode` / `PALETTIER_ICON_MODE`)**:
   - `system` ou `full` *(padrão)*: pastas e mimetypes M3 + **todos os aplicativos instalados** com filtro tonal M3 sobre os ícones originais (intensidade ajustável via `--icon-tint`, padrão `0.90`).
   - `places`: apenas pastas, locais e mimetypes M3.
   - `squircle`: estilo opcional com squircles Material You padronizados para apps principais.
   - `off`: desativa a geração de ícones.
5. **Hot-Reload Atômico no GNOME**:
   - Alterna entre os dois slots `Palettier-M3-A` ↔ `Palettier-M3-B` via `gsettings`, forçando GNOME Shell e Nautilus a recarregar os ícones na hora. O tema anterior é salvo em `.palettier_prev_icon_theme` para restauração no `--uninstall`.

### 4.3. Starship, Ptyxis, Firefox e GNOME Accent (`palettier/targets.py`)

- **Starship (`~/.config/starship.toml`)**: atualiza `[palettes.palettier]` com `palette = 'palettier'`.
- **Ptyxis (`~/.local/share/org.gnome.Ptyxis/palettes/`)**: gera `palettier.palette` (além de caminhos Flatpak se presentes) e configura todos os perfis via GSettings (`org.gnome.Ptyxis.Profile`).
- **Firefox**: localiza perfis em `~/.config/mozilla/firefox/` e `~/.mozilla/firefox/` via `profiles.ini`, ativa `toolkit.legacyUserProfileCustomizations.stylesheets = true;` em `user.js` e grava `chrome/userChrome.css` com suporte a abas horizontais, barra lateral e abas verticais.
- **GNOME 47+**: mapeia a cor de destaque extraída para a chave nativa `accent-color` em `org.gnome.desktop.interface`.

### 4.4. Automação em Tempo Real (`palettier/watch.py`)

- **GSettings + `Gio.FileMonitor`**: reage imediatamente à troca de papel de parede, alteração de `color-scheme` (claro/escuro) ou sobrescrita do arquivo da imagem com debounce de 2,0s.
- **Retorno de Suspensão e Desbloqueio (3 camadas)**:
  1. D-Bus do sistema (`org.freedesktop.login1.Manager.PrepareForSleep` = `false`);
  2. D-Bus da sessão (`org.gnome.ScreenSaver` / `org.freedesktop.ScreenSaver` `ActiveChanged` = `false`);
  3. Fallback por salto monotônico (`time.monotonic()` > 5s entre ciclos).

---

## 5. Estrutura do Projeto e Destinos no Sistema

| Arquivo / Caminho | Origem / Destino | Função |
|---|---|---|
| `pyproject.toml` | Repositório | Metadados do pacote Python e ponto de entrada CLI `palettier` |
| `palettier/palette.py` | Pacote | Motor CAM16 / HCT Material Design 3 e LUTs de tint |
| `palettier/wallpaper.py` | Pacote | Helpers GSettings, detecção de wallpaper e extração de cores |
| `palettier/state.py` | Pacote | Cache de estado `.state` e bloqueio durante transações RPM/DNF |
| `palettier/targets.py` | Pacote | Atualizadores de Starship, Ptyxis, Firefox e GNOME accent |
| `palettier/icons.py` | Pacote | Gerador SVG M3, filtro tonal em apps/AppImages e hot-reload |
| `palettier/sync.py` | Pacote | Orquestrador idempotente de sincronização de temas |
| `palettier/watch.py` | Pacote | Monitoramento em tempo real via GSettings, D-Bus e arquivos |
| `palettier/service.py` | Pacote | Instalação do serviço systemd e desinstalação completa |
| `palettier/cli.py` | Pacote | Interface de linha de comando (`palettier`) |
| `palettier.service` | Repositório | Modelo de referência da unit systemd do usuário |
| `firefox-userChrome.css` | Gerado localmente | Cópia de referência do `userChrome.css` gerado |
| `tests/` | Repositório | Suíte de testes unitários para HCT, ícones, alvos e CLI |
| `~/.local/share/icons/Palettier-M3-{A,B}/` | Gerado | Slots alternados do tema de ícones Material Design 3 |
| `~/.local/share/icons/.palettier_prev_icon_theme` | Gerado | Backup do tema de ícones original do usuário |
| `~/.local/share/icons/.palettier_desktop_icons.json` | Gerado | Mapa de restauração de `.desktop` (ex.: AppImages) |
| `~/.config/systemd/user/palettier.service` | Gerado | Serviço systemd do usuário para `--watch` |
| `~/.config/starship.toml` | Sistema | Paleta dinâmica aplicada ao prompt Starship |
| `~/.local/share/org.gnome.Ptyxis/palettes/palettier.palette` | Sistema / Flatpak | Paleta dinâmica do terminal Ptyxis |
| `~/.config/mozilla/firefox/<perfil>/chrome/userChrome.css` | Sistema | Estilos dinâmicos aplicados ao Firefox |
| `~/.config/mozilla/firefox/<perfil>/user.js` | Sistema | Habilita carregamento do `userChrome.css` |

---

## 6. Guia de Linha de Comando (CLI) e Variáveis de Ambiente

### Variáveis de Ambiente

| Variável | Valores | Padrão | Descrição |
|---|---|---|---|
| `PALETTIER_ICON_MODE` | `system`, `full`, `places`, `squircle`, `off` | `system` | Define o modo padrão do gerador de ícones M3 |
| `PALETTIER_ICON_TINT` | `0.0` a `1.0` | `0.90` | Define a intensidade padrão do filtro tonal M3 nos ícones de apps |

### Comandos Principais

```bash
# Sincronização única com o wallpaper ativo
palettier

# Forçar reaplicação escolhendo modo e intensidade do filtro dos ícones
palettier --icon-mode system --icon-tint 0.90 --force

# Sobrescrever cor de destaque (#HEX) e intensidade de tint manualmente
palettier --accent "#7aa2f7" --tint 0.12 --force

# Sincronizar sem gerar/alterar ícones
palettier --no-icons

# Gerar pré-visualização HTML da paleta M3 e dos ícones
palettier --preview-icons

# Exibir diagnóstico do wallpaper ativo, cor extraída e paleta M3
palettier --info

# Sincronizar a partir de uma imagem específica
palettier --image /caminho/para/wallpaper.jpg

# Executar daemon de monitoramento em tempo real
palettier --watch
```

### Gerenciamento do Serviço e Desinstalação

```bash
# Instalar serviço systemd do usuário
palettier --install-service

# Status, logs em tempo real e reinício
systemctl --user status palettier.service
journalctl --user -u palettier.service -f
systemctl --user restart palettier.service

# Remover apenas o serviço systemd
palettier --uninstall-service

# Desinstalação completa (remove serviço, slots M3, paletas, Firefox e restaura .desktop/ícones originais)
palettier --uninstall
```

---

## 7. Testes Automatizados

Para validar a matemática de cores HCT, contraste WCAG, preservação de silhueta/alpha em PNG e SVG, ponte de AppImages, alternância de slots, alvos de tema e CLI:

```bash
python3 -m unittest discover -s tests -v
```
