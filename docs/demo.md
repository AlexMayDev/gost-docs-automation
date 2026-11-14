# Демо

Два изображения в README показывают один и тот же прогон: разбор «грязной»
выгрузки и первую страницу собранной ведомости.

| Файл | Что это |
| --- | --- |
| [`demo-terminal.png`](demo-terminal.png) | stdout команды `gost-docs`, отрендеренный в изображение |
| [`demo-document.png`](demo-document.png) | первая страница DOCX, отрендеренная через LibreOffice |

## Команда

```bash
gost-docs samples/supplier_export.csv \
  -o output/vedomost.docx \
  --report output/report.json \
  --product АБВГ.000.001
```

Обозначение изделия `АБВГ.000.001` и данные в `samples/` — вымышленные.

## Как получены изображения

1. Команда выше выполняется на `samples/supplier_export.csv`; stdout сохраняется
   в текст.
2. `output/vedomost.docx` конвертируется в PDF headless-режимом LibreOffice:

   ```bash
   soffice --headless --convert-to pdf --outdir output output/vedomost.docx
   ```

3. Первая страница PDF рендерится в PNG через PyMuPDF, страница кладётся на
   светлый фон с тенью.
4. Текст stdout переносится по 108 символов и рисуется моноширинным шрифтом
   Consolas на тёмном фоне с заголовком окна.

Скрипты рендеринга одноразовые и не входят в пакет: они требуют LibreOffice,
PyMuPDF и Pillow, которые не нужны для работы `gost-docs`. Сами изображения
закоммичены, чтобы README не зависел от окружения.

Изображения не участвуют в тестах: `pytest` проверяет содержимое DOCX
(`tests/test_docx.py`), а не его пиксели.

## Веб-интерфейс

Три снимка показывают один и тот же сценарий в локальном браузере:

| Файл | Шаг |
| --- | --- |
| [`web-upload.png`](web-upload.png) | форма загрузки CSV/XLSX |
| [`web-preview.png`](web-preview.png) | предпросмотр 7 позиций и 6 замечаний |
| [`web-result.png`](web-result.png) | готовый документ и ссылки на скачивание |

Снимки сделаны с `gost-docs-web` на `127.0.0.1:8765` при ширине окна 1280 px.
Загружался тот же `samples/supplier_export.csv`, изделие — `АБВГ.000.001`.
Вывод предпросмотра совпадает с CLI: 7 позиций, 8 принятых строк, 3 ошибки,
3 предупреждения, 1 объединённая группа.

Повторить:

```bash
pip install -e ".[web]"
gost-docs-web --port 8765
```

и открыть `http://127.0.0.1:8765/`.
