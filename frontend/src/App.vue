<template>
  <router-view />
</template>

<script setup>
//  Vue Router
</script>

<style>
/*  */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

#app {
  font-family: 'JetBrains Mono', 'Space Grotesk', 'Noto Sans SC', monospace;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  color: #000000;
  background-color: #ffffff;
}

/*  */
::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

::-webkit-scrollbar-track {
  background: #f1f1f1;
}

::-webkit-scrollbar-thumb {
  background: #000000;
}

::-webkit-scrollbar-thumb:hover {
  background: #333333;
}

/* Escala global reducida para que la interfaz quepa completa en pantalla */
html {
  zoom: 0.85;
}

/* Compensar unidades vh bajo zoom para evitar huecos en la parte inferior */
.main-view {
  height: calc(100vh / 0.85) !important;
}

/* Botón de inicio / nuevo proyecto en las cabeceras */
.home-btn {
  margin-left: 16px;
  padding: 5px 12px;
  font-size: 12px;
  font-weight: 600;
  color: #111827;
  background: #F3F4F6;
  border: 1px solid #E5E7EB;
  border-radius: 6px;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.2s ease;
}
.home-btn:hover {
  background: #111827;
  color: #FFFFFF;
}
.header-left {
  display: flex;
  align-items: center;
}

/*  */
button {
  font-family: inherit;
}
</style>
