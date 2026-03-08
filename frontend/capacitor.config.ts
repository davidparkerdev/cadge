import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.thelab.nexus',
  appName: 'Nexus',
  webDir: 'dist',
  plugins: {
    Keyboard: {
      resize: 'body',
      resizeOnFullScreen: true,
    },
  },
  server: {
    // Point to Tailscale IP for development
    url: 'https://davids-mac-mini.taild30c55.ts.net:43400',
    cleartext: true,
  },
};

export default config;
