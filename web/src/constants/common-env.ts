const webConfig = {
    apiUrl: process.env.NODE_ENV === 'development' ? 'http://127.0.0.1:23456' : '',
    appVersion: process.env.NEXT_PUBLIC_APP_VERSION || '0.0.0',
}

export default webConfig
