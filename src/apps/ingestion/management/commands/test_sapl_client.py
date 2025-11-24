"""
Django management command para testar a conexão com a API SAPL.

Uso:
    python manage.py test_sapl_client
"""

from django.core.management.base import BaseCommand
from src.clients.sapl.sapl_client import SaplAPIClient


class Command(BaseCommand):
    help = 'Testa a conexão com a API SAPL'
    
    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE(
            'Testando conexão com API SAPL...'
        ))
        
        try:
            client = SaplAPIClient()
            
            # Buscar apenas 5 normas como teste
            normas = client.fetch_normas(limit=5)
            
            self.stdout.write(self.style.SUCCESS(
                f'✓ Conexão bem-sucedida! {len(normas)} normas retornadas.\n'
            ))
            
            if normas:
                self.stdout.write(self.style.NOTICE('Amostra das normas:'))
                for norma in normas[:3]:
                    tipo_dict = norma.get('tipo', {})
                    tipo = tipo_dict.get('descricao', 'N/A') if isinstance(tipo_dict, dict) else str(tipo_dict)
                    numero = norma.get('numero', 'N/A')
                    ano = norma.get('ano', 'N/A')
                    ementa = norma.get('ementa', '')[:80]
                    
                    self.stdout.write(
                        f'\n  [{norma.get("id")}] {tipo} {numero}/{ano}\n'
                        f'  Ementa: {ementa}...'
                    )
            
            client.close()
            
            self.stdout.write(self.style.SUCCESS(
                '\n✓ Teste concluído com sucesso!'
            ))
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(
                f'✗ Falha no teste: {str(e)}'
            ))
            raise

