# 第三方运行时 · Vendored runtime

本目录随共享运行时发布为 `<slug>/viz/assets/vendor/`。页面不直接加载这里的文件：造型核心 `../solid-core.js` 以相对自己的路径导入它们，`kit.solid`（`theme/viz/kit.js`）第一次被调用时才取这个核心，没有画实体的页面不多下载任何东西；视频引擎导入同一个核心。语法检查（`viz-validate`）跳过本目录。

These files are published with the shared runtime as `<slug>/viz/assets/vendor/`. Pages never load them directly: the modelling core `../solid-core.js` imports them relative to itself, and the first call of `kit.solid` (`theme/viz/kit.js`) fetches that core, so a page that draws no solid downloads nothing more; the film engine imports the same core. The syntax check (`viz-validate`) skips this directory.

## three.js

| | |
| --- | --- |
| 包 package | three@0.183.2（npm，2026-02-28 发布） |
| 来源 source | `npm pack three@0.183.2`，取包内 `build/three.module.min.js` 与它导入的 `build/three.core.min.js`，原样复制，未改一个字节 |
| 许可证 licence | MIT，见 `three.LICENSE`（包内 `LICENSE`）；两个文件开头的 `@license` 头保留 |
| 体积 size | 85010 + 100241 字节（gzip -9），未压缩 359 158 + 382 617 字节 |

校验和 checksums (sha256, checked by `tools/tests/test_viz_solid.py`):

- `0a61c95f14e0fa015b3083475c73424f360e5f6f5b74c282b50fdbc2f4c228fc`  `three.module.min.js`
- `0a9c2f0672c7b8d993ba7639e71919db181ca50c9dff99c78476d3e19057ca9c`  `three.core.min.js`

升级：换成新版本的同名两个文件与 `LICENSE`，更新上表与校验和，运行 `PYTHONPATH=tools .venv/bin/python -m unittest tools.tests.test_viz_solid` 与示例专著的浏览器测试，并在截图里亲眼看实体页面。

To upgrade: replace the two files and the licence with those of the new version, update the table and the checksums, run `tools/tests/test_viz_solid.py` and the example book's browser suites, and look at the solid pages in the screenshots.
