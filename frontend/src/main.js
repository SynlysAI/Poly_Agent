import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'

import App from './App.vue'
import router from './router'
import './style.css'
import { i18nPlugin } from './i18n/index.js'

const app = createApp(App)
app.use(ElementPlus)
app.use(i18nPlugin)
app.use(router)
app.mount('#app')
