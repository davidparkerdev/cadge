/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        surface: {
          primary: '#0f0f0f',
          secondary: '#171717',
          tertiary: '#262626',
        },
        accent: '#00d4ff',
        text: {
          primary: '#fafafa',
          secondary: '#a3a3a3',
        },
        border: {
          DEFAULT: '#262626',
          hover: '#404040',
        },
      },
      fontFamily: {
        mono: ['Monaco', 'Menlo', 'Ubuntu Mono', 'monospace'],
      },
    },
  },
  plugins: [],
}
