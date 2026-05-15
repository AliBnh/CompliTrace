import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      boxShadow: {
        soft: '0 10px 40px rgba(2, 6, 23, 0.45)',
        card: '0 1px 3px rgba(0, 0, 0, 0.08)',
        'card-md': '0 4px 12px rgba(0, 0, 0, 0.10)',
      },
      colors: {
        brand: {
          50: '#EFF6FF',
          100: '#DBEAFE',
          400: '#60A5FA',
          500: '#3B82F6',
          600: '#2563EB',
          700: '#1D4ED8',
        },
      },
    },
  },
  plugins: [],
} satisfies Config
