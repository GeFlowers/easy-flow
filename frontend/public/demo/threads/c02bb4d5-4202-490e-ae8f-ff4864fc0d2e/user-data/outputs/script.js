// 《傲慢与偏见》交互功能

document.addEventListener("DOMContentLoaded", () => {
  // 导航栏滚动效果
  initNavigation();

  // 引言轮播器
  initQuotesSlider();

  // 滚动显现动画
  initScrollReveal();

  // 锚点链接平滑滚动
  initSmoothScroll();
});

// ============================================
// 导航栏滚动效果
// ============================================
/**
 * 封装测试或脚本中的可复用操作，使调用处能够明确复用 initNavigation 的约定。
 */
function initNavigation() {
  const nav = document.querySelector(".nav");
  let lastScroll = 0;

  window.addEventListener("scroll", () => {
    const currentScroll = window.pageYOffset;

    // 添加或移除 scrolled 类
    if (currentScroll > 100) {
      nav.classList.add("scrolled");
    } else {
      nav.classList.remove("scrolled");
    }

    lastScroll = currentScroll;
  });
}

// ============================================
// 引言轮播器
// ============================================
/**
 * 封装测试或脚本中的可复用操作，使调用处能够明确复用 initQuotesSlider 的约定。
 */
function initQuotesSlider() {
  const quotes = document.querySelectorAll(".quote-card");
  const dots = document.querySelectorAll(".quote-dot");
  let currentIndex = 0;
  let autoSlideInterval;

  /**
   * 封装测试或脚本中的可复用操作，使调用处能够明确复用 showQuote 的约定。

   */

  function showQuote(index) {
    // 移除全部引言和圆点的 active 类
    quotes.forEach((quote) => quote.classList.remove("active"));
    dots.forEach((dot) => dot.classList.remove("active"));

    // 为当前引言和圆点添加 active 类
    quotes[index].classList.add("active");
    dots[index].classList.add("active");

    currentIndex = index;
  }

  /**
   * 封装测试或脚本中的可复用操作，使调用处能够明确复用 nextQuote 的约定。

   */

  function nextQuote() {
    const nextIndex = (currentIndex + 1) % quotes.length;
    showQuote(nextIndex);
  }

  // 圆点点击处理器
  dots.forEach((dot, index) => {
    dot.addEventListener("click", () => {
      showQuote(index);
      resetAutoSlide();
    });
  });

  // 自动轮播功能
  /**
   * 封装测试或脚本中的可复用操作，使调用处能够明确复用 startAutoSlide 的约定。
   */
  function startAutoSlide() {
    autoSlideInterval = setInterval(nextQuote, 6000);
  }

  /**
   * 封装测试或脚本中的可复用操作，使调用处能够明确复用 resetAutoSlide 的约定。

   */

  function resetAutoSlide() {
    clearInterval(autoSlideInterval);
    startAutoSlide();
  }

  // 启动自动轮播
  startAutoSlide();

  // 悬停时暂停
  const slider = document.querySelector(".quotes-slider");
  slider.addEventListener("mouseenter", () => clearInterval(autoSlideInterval));
  slider.addEventListener("mouseleave", startAutoSlide);
}

// ============================================
// 滚动显现动画
// ============================================
/**
 * 封装测试或脚本中的可复用操作，使调用处能够明确复用 initScrollReveal 的约定。
 */
function initScrollReveal() {
  const revealElements = document.querySelectorAll(
    ".about-content, .character-card, .theme-item, .section-header",
  );

  const revealOptions = {
    threshold: 0.15,
    rootMargin: "0px 0px -50px 0px",
  };

  const revealObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry, index) => {
      if (entry.isIntersecting) {
        // 为网格项添加错峰延迟
        const delay =
          entry.target.classList.contains("character-card") ||
          entry.target.classList.contains("theme-item")
            ? index * 100
            : 0;

        setTimeout(() => {
          entry.target.classList.add("reveal");
          entry.target.style.opacity = "1";
          entry.target.style.transform = "translateY(0)";
        }, delay);

        revealObserver.unobserve(entry.target);
      }
    });
  }, revealOptions);

  revealElements.forEach((el) => {
    el.style.opacity = "0";
    el.style.transform = "translateY(30px)";
    el.style.transition =
      "opacity 0.8s cubic-bezier(0.16, 1, 0.3, 1), transform 0.8s cubic-bezier(0.16, 1, 0.3, 1)";
    revealObserver.observe(el);
  });
}

// ============================================
// 锚点链接平滑滚动
// ============================================
/**
 * 封装测试或脚本中的可复用操作，使调用处能够明确复用 initSmoothScroll 的约定。
 */
function initSmoothScroll() {
  document.querySelectorAll('a[href^="#"]').forEach((anchor) => {
    anchor.addEventListener("click", function (e) {
      e.preventDefault();
      const target = document.querySelector(this.getAttribute("href"));

      if (target) {
        const navHeight = document.querySelector(".nav").offsetHeight;
        const targetPosition =
          target.getBoundingClientRect().top + window.pageYOffset - navHeight;

        window.scrollTo({
          top: targetPosition,
          behavior: "smooth",
        });
      }
    });
  });
}

// ============================================
// 首屏视差效果
// ============================================
window.addEventListener("scroll", () => {
  const scrolled = window.pageYOffset;
  const heroPattern = document.querySelector(".hero-pattern");

  if (heroPattern && scrolled < window.innerHeight) {
    heroPattern.style.transform = `translateY(${scrolled * 0.3}px) rotate(${scrolled * 0.02}deg)`;
  }
});

// ============================================
// 角色卡片悬停效果
// ============================================
document.querySelectorAll(".character-card").forEach((card) => {
  card.addEventListener("mouseenter", function () {
    this.style.zIndex = "10";
  });

  card.addEventListener("mouseleave", function () {
    this.style.zIndex = "1";
  });
});
