# Решение: стек

Type: grilling
Status: resolved

## Question

На чём писать?

## Answer

GTK4 + Python (PyGObject), libadwaita где уместно. Всё уже стоит на машине, прототип — за вечер, нативный вид GNOME.

Rust (gtk4-rs) — условие выхода в продукт: если прототип покажет неприемлемые память, время старта или вес упаковки. Tauri и Electron отклонены: вес и невозможность честного layer-shell поведения.
