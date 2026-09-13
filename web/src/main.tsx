import React from 'react';
import ReactDOM from 'react-dom/client';
import { MantineProvider, createTheme } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import '@mantine/core/styles.css';
import './styles.css';
import App from './App';

const theme = createTheme({
  fontFamily: '"Segoe UI", Arial, sans-serif', primaryColor: 'rust', defaultRadius: 'sm',
  colors: { rust: ['#fcece6','#f4d3c6','#eab49f','#df947b','#d6775a','#c65b3d','#b3472d','#963b26','#7f3220','#672819'] },
  headings: { fontFamily: 'Georgia, "Times New Roman", serif', fontWeight: '400' },
  components: { Modal: { defaultProps: { closeButtonProps: { 'aria-label': 'Close dialog' } } } },
});
const queryClient = new QueryClient({defaultOptions:{queries:{retry:1,refetchOnWindowFocus:false},mutations:{retry:false}}});
ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><MantineProvider theme={theme} forceColorScheme="light"><QueryClientProvider client={queryClient}><App/></QueryClientProvider></MantineProvider></React.StrictMode>);
