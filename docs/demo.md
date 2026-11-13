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
