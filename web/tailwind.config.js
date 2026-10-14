/** @type {import('tailwindcss').Config} */
// Дизайн-токены КАРКАС (Д3 §7). Значения синхронизированы с CSS-переменными в src/styles.css.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: "#0F766E", // основные действия, активный шаг, «утверждено»
          dark: "#0B5D57",
          bg: "#E6F4F2",
        },
        ink: {
          DEFAULT: "#1F3A5F", // заголовки и навигация
          muted: "#4B5F7A",
        },
        danger: { DEFAULT: "#B91C1C", bg: "#FEF2F2" }, // ошибки, несходящиеся суммы
        warning: { DEFAULT: "#92400E", bg: "#FEF3C7" }, // предупреждения
        success: { DEFAULT: "#166534", bg: "#DCFCE7" }, // пройденные проверки
        surface: "#FFFFFF",
        canvas: "#F6F8FA",
        line: "#D7DFE9",
      },
      fontFamily: {
        sans: ['"PT Sans"', "Arial", "sans-serif"],
      },
      fontSize: {
        caption: "12.5px", // подписи
        base: "14px", // текст
        subtitle: "16px", // подзаголовки
        title: "22px", // заголовок экрана
      },
      spacing: {
        // сетка отступов 4/8/12/16/24 совпадает со стандартной шкалой Tailwind
        xs: "4px",
        sm: "8px",
        md: "12px",
        lg: "16px",
        xl: "24px",
      },
      borderRadius: {
        btn: "8px", // кнопки
        card: "12px", // карточки
      },
      outlineOffset: {
        2: "2px",
      },
      boxShadow: {
        card: "0 1px 2px rgba(31, 58, 95, 0.08), 0 4px 12px rgba(31, 58, 95, 0.06)",
        drawer: "-8px 0 24px rgba(31, 58, 95, 0.18)",
      },
    },
  },
  plugins: [],
};
