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
    url: 'http://100.67.60.42:33400',
    cleartext: true,
  },
};

export default config;
