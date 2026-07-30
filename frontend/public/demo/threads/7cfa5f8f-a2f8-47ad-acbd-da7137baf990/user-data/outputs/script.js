// “2026 地平线”演示页的交互功能。

/** 在 DOM 就绪后初始化主题、导航、滚动动画与页脚年份。 */
document.addEventListener("DOMContentLoaded", function () {
  // 主题切换控件。
  const themeToggle = document.getElementById("themeToggle");
  const themeIcon = themeToggle.querySelector("i");

  // 优先采用已保存的主题，其次采用系统深色偏好。
  const savedTheme = localStorage.getItem("theme");
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;

  if (savedTheme === "dark" || (!savedTheme && prefersDark)) {
    document.documentElement.setAttribute("data-theme", "dark");
    themeIcon.className = "fas fa-sun";
  }

  /** 在保留用户选择的同时切换深浅主题及对应图标。 */
  themeToggle.addEventListener("click", function () {
    const currentTheme = document.documentElement.getAttribute("data-theme");

    if (currentTheme === "dark") {
      document.documentElement.removeAttribute("data-theme");
      themeIcon.className = "fas fa-moon";
      localStorage.setItem("theme", "light");
    } else {
      document.documentElement.setAttribute("data-theme", "dark");
      themeIcon.className = "fas fa-sun";
      localStorage.setItem("theme", "dark");
    }
  });

  // 导航锚点平滑滚动。
  document.querySelectorAll('a[href^="#"]').forEach((anchor) => {
    /** 扣除固定导航栏高度后，平滑滚动到目标锚点。 */
    anchor.addEventListener("click", function (e) {
      e.preventDefault();

      const targetId = this.getAttribute("href");
      if (targetId === "#") return;

      const targetElement = document.querySelector(targetId);
      if (targetElement) {
        const headerHeight = document.querySelector(".navbar").offsetHeight;
        const targetPosition = targetElement.offsetTop - headerHeight - 20;

        window.scrollTo({
          top: targetPosition,
          behavior: "smooth",
        });
      }
    });
  });

  // 导航栏滚动效果。
  const navbar = document.querySelector(".navbar");
  let lastScrollTop = 0;

  /** 根据滚动方向隐藏或显示导航栏，并在离开顶部后添加阴影。 */
  window.addEventListener("scroll", function () {
    const scrollTop = window.pageYOffset || document.documentElement.scrollTop;

    // 滚动时隐藏或显示导航栏。
    if (scrollTop > lastScrollTop && scrollTop > 100) {
      navbar.style.transform = "translateY(-100%)";
    } else {
      navbar.style.transform = "translateY(0)";
    }

    lastScrollTop = scrollTop;

    // 离开顶部后添加阴影。
    if (scrollTop > 10) {
      navbar.style.boxShadow = "var(--shadow-md)";
    } else {
      navbar.style.boxShadow = "none";
    }
  });

  // 滚动进入视口时播放元素动画。
  const observerOptions = {
    threshold: 0.1,
    rootMargin: "0px 0px -50px 0px",
  };

  /** 为首次进入视口的卡片添加淡入类，并停止继续观察该卡片。 */
  const observer = new IntersectionObserver(function (entries) {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add("fade-in");
        observer.unobserve(entry.target);
      }
    });
  }, observerOptions);

  // 观察需要播放动画的元素。
  document
    .querySelectorAll(
      ".trend-card, .opportunity-card, .challenge-card, .highlight-card",
    )
    .forEach((el) => {
      observer.observe(el);
    });

  // 统计数字递增动画。
  const stats = document.querySelectorAll(".stat-number");

  const statsObserver = new IntersectionObserver(
    /** 在统计数字进入视口时，以固定步数逐渐递增至目标数值。 */
    function (entries) {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          const stat = entry.target;
          const targetValue = parseInt(stat.textContent);
          let currentValue = 0;
          const increment = targetValue / 50;
          const duration = 1500;
          const stepTime = Math.floor(duration / 50);

          const timer = setInterval(() => {
            currentValue += increment;
            if (currentValue >= targetValue) {
              stat.textContent = targetValue;
              clearInterval(timer);
            } else {
              stat.textContent = Math.floor(currentValue);
            }
          }, stepTime);

          statsObserver.unobserve(stat);
        }
      });
    },
    { threshold: 0.5 },
  );

  stats.forEach((stat) => {
    statsObserver.observe(stat);
  });

  // 卡片悬停效果。
  document
    .querySelectorAll(".trend-card, .opportunity-card, .challenge-card")
    .forEach((card) => {
      /** 鼠标进入卡片时提升其层级，避免被相邻卡片遮挡。 */
      card.addEventListener("mouseenter", function () {
        this.style.zIndex = "10";
      });

      /** 鼠标离开卡片时恢复默认层级。 */
      card.addEventListener("mouseleave", function () {
        this.style.zIndex = "1";
      });
    });

  // 页脚当前年份。
  const currentYear = new Date().getFullYear();
  const yearElement = document.querySelector(".copyright p");
  if (yearElement) {
    yearElement.textContent = yearElement.textContent.replace(
      "2026",
      currentYear,
    );
  }

  // 初始化页面动画。
  setTimeout(() => {
    document.body.style.opacity = "1";
  }, 100);
});

// 添加首屏淡入所需的样式。
const style = document.createElement("style");
style.textContent = `
    body {
        opacity: 0;
        transition: opacity 0.5s ease-in;
    }
    
    .fade-in {
        animation: fadeIn 0.8s ease-out forwards;
    }
    
    @keyframes fadeIn {
        from {
            opacity: 0;
            transform: translateY(20px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }
`;
document.head.appendChild(style);
