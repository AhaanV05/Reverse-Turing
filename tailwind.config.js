/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./templates/*.html"],
  theme: {
    extend: {
      colors:{
        "neongreen": "#39FF14",
        "mattblack": "#151515",
        "adminblue": "#04d9ff"
      },
      fontFamily:{
        "pixelify": "'Pixel Operator Mono', monospace"
      }
    },
  },
  plugins: [],
}

