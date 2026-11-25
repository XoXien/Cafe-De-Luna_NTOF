from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [path('admin/', admin.site.urls), path('', include('cafe.urls'))]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

admin.site.site_header = 'Coffee de Luna Administration'
admin.site.site_title = 'Coffee de Luna'
admin.site.index_title = 'Account and catalog administration'
