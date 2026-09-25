// Проверка ui-i18n.js через обходчик DOM, как в браузере. Django-тесты JS не
// исполняют, а прошлая проверка звала qmsTranslate в обход обходчика и не
// увидела, что по-русски пункт меню показывал ключ «раздел:Склад».
//
// Запуск из корня репозитория:
//   docker run --rm -v "$PWD/services/qms/static/js:/js" \
//     -v "$PWD/services/qms/apps/accounts/tests:/t" node:20-slim node /t/check_i18n_dom.js

const fs = require("fs");

const noop = () => {};
let language = "ru";
let onReady = null;

function element(attrs) {
  return {
    nodeType: 1,
    getAttribute: name => (name in attrs ? attrs[name] : null),
    hasAttribute: name => name in attrs,
    setAttribute: noop,
    closest: () => null,
  };
}

const menuText = { nodeType: 3, nodeValue: "Склад", parentElement: element({ "data-i18n": "раздел:Склад" }) };
const stageText = { nodeType: 3, nodeValue: "Склад", parentElement: element({}) };
const statusText = { nodeType: 3, nodeValue: "На складе", parentElement: element({}) };
const nodes = [menuText, stageText, statusText];

global.localStorage = { getItem: () => language, setItem: noop };
global.navigator = { language: "ru" };
global.Node = { TEXT_NODE: 3, ELEMENT_NODE: 1 };
global.NodeFilter = { SHOW_ELEMENT: 1, SHOW_TEXT: 4, FILTER_ACCEPT: 1, FILTER_REJECT: 2 };
global.document = {
  documentElement: {},
  body: element({}),
  title: "",
  addEventListener: (name, handler) => { if (name === "DOMContentLoaded") onReady = handler; },
  dispatchEvent: noop,
  querySelectorAll: () => [],
  createTreeWalker: () => { let i = 0; return { nextNode: () => nodes[i++] || null }; },
};
global.window = global;
global.MutationObserver = function () { return { observe: noop }; };
global.CustomEvent = function () {};
global.confirm = () => true;
global.alert = noop;

eval(fs.readFileSync("/js/ui-i18n.js", "utf8"));

const expected = {
  ru: { menu: "Склад", stage: "Склад", status: "На складе" },
  en: { menu: "Warehouse", stage: "Склад", status: "In stock" },
  kk: { menu: "Қойма", stage: "Склад", status: "Қоймада" },
};

let failed = 0;
for (const lang of ["ru", "en", "kk", "ru"]) {  // и обратно на русский
  language = lang;
  onReady();
  const got = { menu: menuText.nodeValue, stage: stageText.nodeValue, status: statusText.nodeValue };
  for (const key of Object.keys(got)) {
    const ok = got[key] === expected[lang][key];
    if (!ok) failed++;
    console.log(`  ${ok ? "ok " : "НЕТ"} ${lang}  ${key.padEnd(7)} ${got[key]}${ok ? "" : `   (ждали ${expected[lang][key]})`}`);
  }
}
console.log(failed ? `\n${failed} не прошло` : "\nвсё сошлось");
process.exit(failed ? 1 : 0);
