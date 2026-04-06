import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      boxShadow: {
        soft: '0 10px 40px rgba(2, 6, 23, 0.45)',
      },
      colors: {
        brand: {
          500: '#22d3ee',
          600: '#06b6d4',
        },
      },
    },
  },
  plugins: [],
} satisfies Config
