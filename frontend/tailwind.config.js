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
          bg:      '#0a0e1a',
          surface: '#111827',
          card:    '#1a2235',
          border:  '#2a3550',
          accent:  '#3b82f6',
          teal:    '#20d0b4',
          success: '#22c55e',
          warning: '#f59e0b',
          danger:  '#ef4444',
          muted:   '#6b7280',
        },
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
