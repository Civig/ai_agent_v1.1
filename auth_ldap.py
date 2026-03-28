from datetime import datetime, timedelta
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional, Dict, Any
import logging
from ldap3 import Server, Connection, ALL, NTLM, core
from ldap3.core.exceptions import LDAPException, LDAPBindError

from config import settings

# Настройка логирования
logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)


class LDAPAuth:
    """Аутентификация через Active Directory напрямую по LDAP"""
    
    def __init__(self):
        self.ldap_server = settings.LDAP_SERVER.replace('ldap://', '')
        self.domain = settings.LDAP_DOMAIN
        self.base_dn = settings.LDAP_BASE_DN
        self.netbios_domain = settings.LDAP_NETBIOS_DOMAIN

    def authenticate(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        """
        Проверка логина/пароля напрямую в AD
        
        Args:
            username: Имя пользователя (без домена)
            password: Пароль пользователя
            
        Returns:
            Dict с информацией о пользователе или None
        """
        try:
            logger.info(f"Authenticating user: {username}")
            
            # Формируем правильные форматы для AD
            user_principal = f"{username}@{self.domain}"  # user@domain.com
            ntlm_user = f"{self.netbios_domain}\\{username}"  # DOMAIN\user
            
            # Пробуем NTLM аутентификацию (наиболее надежно для Windows AD)
            try:
                server = Server(self.ldap_server, get_info=ALL)
                conn = Connection(
                    server,
                    user=ntlm_user,
                    password=password,
                    authentication=NTLM,
                    auto_bind=True  # Сразу пробуем подключиться
                )
                logger.debug(f"NTLM auth successful for {username}")
                
            except LDAPBindError:
                # Если NTLM не сработал, пробуем простой bind
                try:
                    conn = Connection(
                        server,
                        user=user_principal,
                        password=password,
                        auto_bind=True
                    )
                    logger.debug(f"Simple bind successful for {username}")
                except LDAPBindError:
                    logger.warning(f"LDAP bind failed for {username}")
                    return None
            except LDAPException as e:
                logger.error(f"LDAP connection error: {str(e)}")
                return None
            
            # Если дошли сюда - пользователь аутентифицирован!
            
            # Получаем информацию о пользователе
            user_info = self._get_user_info(conn, username)
            
            # Закрываем соединение
            conn.unbind()
            
            logger.info(f"User {username} authenticated successfully")
            return user_info
            
        except Exception as e:
            logger.error(f"Authentication error: {str(e)}")
            return None
    
    def _get_user_info(self, conn: Connection, username: str) -> Dict[str, Any]:
        """Получение информации о пользователе из AD"""
        try:
            # Поиск пользователя в AD
            search_filter = f"(&(objectClass=user)(sAMAccountName={username}))"
            
            conn.search(
                search_base=self.base_dn,
                search_filter=search_filter,
                attributes=['displayName', 'mail', 'memberOf', 'givenName', 'sn', 'userPrincipalName']
            )
            
            if not conn.entries:
                # Если не нашли в AD, возвращаем базовую информацию
                return {
                    'username': username.lower(),
                    'display_name': username.capitalize(),
                    'email': f"{username}@{self.domain}",
                    'groups': ['domain_users']
                }
            
            entry = conn.entries[0]
            
            # Извлекаем группы пользователя
            groups = []
            if hasattr(entry, 'memberOf') and entry.memberOf:
                for group_dn in entry.memberOf:
                    # Извлекаем CN (Common Name) из DN
                    if ',' in str(group_dn):
                        cn_part = str(group_dn).split(',')[0]
                        if cn_part.startswith('CN='):
                            groups.append(cn_part[3:])
            
            # Формируем информацию
            user_info = {
                'username': username.lower(),
                'display_name': str(entry.displayName) if hasattr(entry, 'displayName') and entry.displayName else username.capitalize(),
                'email': str(entry.mail) if hasattr(entry, 'mail') and entry.mail else f"{username}@{self.domain}",
                'first_name': str(entry.givenName) if hasattr(entry, 'givenName') and entry.givenName else '',
                'last_name': str(entry.sn) if hasattr(entry, 'sn') and entry.sn else '',
                'user_principal': str(entry.userPrincipalName) if hasattr(entry, 'userPrincipalName') and entry.userPrincipalName else f"{username}@{self.domain}",
                'groups': groups
            }
            
            return user_info
            
        except Exception as e:
            logger.error(f"Error getting user info: {str(e)}")
            # Возвращаем базовую информацию в случае ошибки
            return {
                'username': username.lower(),
                'display_name': username.capitalize(),
                'email': f"{username}@{self.domain}",
                'groups': ['domain_users']
            }


# Создаем экземпляр для использования
ldap_auth = LDAPAuth()


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Создание JWT токена"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Optional[Dict[str, Any]]:
    """Получение текущего пользователя из JWT токена"""
    token = None

    # Проверяем куки
    cookie_token = request.cookies.get("access_token")
    if cookie_token:
        if cookie_token.startswith("Bearer "):
            token = cookie_token.replace("Bearer ", "")
        else:
            token = cookie_token

    # Проверяем заголовок
    if not token and credentials:
        token = credentials.credentials

    if not token:
        return None

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None

        return {
            "username": username,
            "display_name": payload.get("display_name", username),
            "email": payload.get("email", f"{username}@{settings.LDAP_DOMAIN}"),
            "groups": payload.get("groups", [])
        }
    except JWTError as e:
        logger.error(f"JWT decode error: {str(e)}")
        return None


async def get_current_user_required(
    current_user: Optional[Dict[str, Any]] = Depends(get_current_user)
) -> Dict[str, Any]:
    """Защита эндпоинтов - требует аутентификации"""
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user
