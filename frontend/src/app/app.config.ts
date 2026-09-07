import { ApplicationConfig, inject, provideBrowserGlobalErrorListeners, provideAppInitializer } from '@angular/core';
import { provideRouter, TitleStrategy } from '@angular/router';

import { AuthService } from './api/auth.service';
import { PageTitle } from './page-title';
import { routes } from './app.routes';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes),
    provideAppInitializer(() => inject(AuthService).refresh()),
    { provide: TitleStrategy, useClass: PageTitle },
  ]
};
