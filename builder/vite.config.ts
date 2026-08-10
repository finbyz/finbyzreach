import path from 'path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react'
import proxyOptions from './proxyOptions.ts';

// https://vitejs.dev/config/
export default defineConfig({
	plugins: [react()],
	server: {
		port: 8080,
		host: '0.0.0.0',
		proxy: proxyOptions
	},
	resolve: {
		alias: {
			'@': path.resolve(__dirname, 'src')
		}
	},
	build: {
		outDir: '../finbyzreach/public/builder',
		emptyOutDir: true,
		target: 'es2020',
		rollupOptions: {
			output: {
				manualChunks(id) {
					if (id.includes('node_modules/react') || id.includes('node_modules/react-dom')) return 'react-vendor'
					if (id.includes('node_modules/frappe-react-sdk') || id.includes('node_modules/frappe-js-sdk') || id.includes('node_modules/swr')) return 'frappe-sdk'
					if (id.includes('node_modules/@dnd-kit')) return 'drag-drop'
					if (id.includes('node_modules/lucide-react')) return 'icons'
				},
			},
		},
	},
});
