/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        da: {
          bg:      '#f5f7fb',
          surface: '#ffffff',
          card:    '#ffffff',
          border:  '#e6edf6',
          accent:  '#3b82f6',
          teal:    '#20c997',
          success: '#22c55e',
          warning: '#f59e0b',
          danger:  '#ef4444',
          muted:   '#6b7280',
        },
      },
      boxShadow: {
        'da-sm': '0 6px 12px rgba(15,23,42,0.06)',
        'da-md': '0 18px 48px rgba(15,23,42,0.08)',
      },
      borderRadius: {
        'da-sm': '8px',
        'da-md': '12px',
        'da-lg': '16px',
      },
      fontFamily: {
        mono:    ['JetBrains Mono', 'monospace'],
        display: ['Rajdhani', 'sans-serif'],
      },
      animation: {
        'pulse-slow': 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
    },
  },
  plugins: [],
}
