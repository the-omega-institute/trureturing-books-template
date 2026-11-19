# 容器工具链

书籍构建需要的浏览器、字体与系统库在镜像构建时安装。普通 CI 作业拉取完整镜像后，使用预装依赖，不再执行 apt、pip、npm 或下载语音模型。GitHub 与 trureturing 的引用核验、发布和远程产物缓存仍需要网络。

## 镜像与版本

官方 [Playwright 镜像](https://playwright.dev/docs/docker) 提供浏览器与系统依赖，但不包含本模板的完整出版工具链。`tools/container/Dockerfile` 在与锁文件一致的 `mcr.microsoft.com/playwright:v1.56.1-noble`（固定摘要）上增加：

- Python 3.12 与 `requirements.txt` 的 Pandoc、Typst、epubcheck；Java、mdBook 0.5.4（校验发布附件 SHA-256）；
- `package-lock.json` 的 KaTeX、Slidev、Playwright 与字体包；
- 中英文字体与经校验的 PDF 字体、ffmpeg；
- `theme/film/requirements.txt` 的视频与语音依赖、Kokoro 模型及音色。

上游仓库的 `Toolchain image` 工作流构建 Linux amd64 镜像。先在断网容器中实际生成 PDF、EPUB、语音并启动 Chromium，再检查、运行单元测试及浏览器测试、完整构建示例书，全部成功后才推送：

```text
ghcr.io/the-omega-institute/trureturing-books-toolchain:sha-<完整提交 SHA>
```

默认分支更新 `latest`，容器集成检查通过后将镜像摘要登记在按 Git 输入内容生成的 `inputs-…` 标签下。版本 tag 读取相同输入的已验证摘要，直接为它添加同名镜像标签和提交标签。若该输入刚合入主干，发布等待对应的镜像验证完成。PR 只在镜像输入变化时构建和验证。下游仓库不运行镜像发布工作流。首次发布后需把 GHCR 包设为公开，使其他书库及 fork PR 可以匿名拉取；不要把私有包的令牌写进工作流。生产 CI 使用工作流摘要中的 `@sha256:…` 固定镜像，不跟随 `latest`。

## 本地运行

在干净的书库 checkout 中运行（把镜像替换为已发布的摘要）：

```bash
docker run --rm --init --ipc=host \
  --volume "$PWD:/work" --workdir /work \
  ghcr.io/the-omega-institute/trureturing-books-toolchain@sha256:<digest> \
  bash -euo pipefail -c 'python /opt/tbook/container/prepare.py; ./tbook check; ./tbook build all'
```

`prepare.py` 逐一核对镜像所记录的依赖文件 SHA-256，再把镜像中的 Node 包与字体连接到 checkout。依赖文件发生变化时立即失败，提示重建镜像，避免无声地使用旧依赖。已有的 `node_modules` 或 `.cache/fonts` 不会被覆盖；请使用干净 checkout。挂载目录中的构建产物在 Linux 上默认归 root 所有。

## GitHub Actions

作业可通过 `container.image` 使用该镜像，保留 `.github/actions/setup`（自动识别镜像并核对依赖）：

```yaml
jobs:
  build:
    runs-on: ubuntu-24.04
    container:
      image: ghcr.io/the-omega-institute/trureturing-books-toolchain@sha256:<digest>
      options: --init --ipc=host
    defaults:
      run:
        shell: bash
    steps:
      - uses: actions/checkout@v5
      - uses: ./.github/actions/setup
        with:
          browsers: 'true'
          fonts: 'true'
          films: 'true'
      - run: ./tbook build all
```

GitHub Actions 容器默认的 shell 是 `sh`，本模板工作流中的脚本需要上面的 `shell: bash`。镜像不包含任何书的正文、trureturing 账本或凭据。完整 Lean 深度验证仍由独立的 `lean-verify.yml` 工作流提供。

## 重建

```bash
docker build --file tools/container/Dockerfile --tag tbook-toolchain:local .
docker run --rm --init --ipc=host --network=none tbook-toolchain:local \
  python /opt/tbook/container/smoke.py
```

修改依赖时先更新对应锁文件，再构建并验证新镜像，最后把消费者的镜像摘要更新到新值。Playwright 升级还必须同步 Dockerfile 的基础镜像版本及摘要。工作流也每周重建、验证镜像以吸收系统安全更新；固定摘要的消费者按需升级。
