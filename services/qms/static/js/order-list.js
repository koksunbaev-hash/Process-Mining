/* Все позиции заказа - по щелчку, прямо в карточке.
 *
 * По умолчанию видно три ряда: иначе один заводской заказ на три десятка
 * позиций вытягивал бы весь ряд карточек на высоту экрана. Но прятать состав
 * совсем нельзя - за ним сюда и заходят, а уводить ради этого на страницу
 * заказа значит терять из виду остальные.
 */
(function () {
  document.querySelectorAll("[data-products-toggle]").forEach((toggle) => {
    toggle.dataset.label = toggle.textContent.trim();
  });

  // Слушатель на документе, а не на кнопках: их столько же, сколько заказов на
  // странице, и вешать на каждую по обработчику незачем.
  document.addEventListener("click", (event) => {
    const toggle = event.target.closest("[data-products-toggle]");
    if (!toggle) return;

    const card = toggle.closest(".order-history-card");
    const clip = card && card.querySelector(".order-products-clip");
    if (!clip) return;

    const opened = clip.classList.toggle("is-whole");
    toggle.setAttribute("aria-expanded", opened ? "true" : "false");
    // Число в скобках - счёт позиций, и при сворачивании оно должно вернуться.
    toggle.textContent = opened ? "Свернуть" : toggle.dataset.label;
  });
})();
