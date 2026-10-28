# Research: публикация и ревью в Snap Store

Type: research
Status: open
Blocked by:

## Question

Какой полный путь публикации strict GUI-снапа в Snap Store и что проверяет
ревью?

Выяснить по первоисточникам (snapcraft.io docs, store review policy, snapd):

- регистрация аккаунта, имени `lurknotes`, Publisher Agreement;
- обязательные поля листинга: license, contact, homepage, категория,
  скриншоты, иконка, description;
- какие интерфейсы/особенности (`x11`, `autostart`, `desktop`) триггерят
  ручное ревью; чего избегать (classic, system-files);
- каналы, ревизии, `snapcraft upload`/`release`, откат, публикация в `stable`;
- требования к сборке (`snapcraft` + LXD/Multipass), можно ли собрать без
  root/виртуалки;
- что видит пользователь при `snap install` (permissions, autostart).

Ответ — пошаговый чек-лист публикации с командами и ссылками.
