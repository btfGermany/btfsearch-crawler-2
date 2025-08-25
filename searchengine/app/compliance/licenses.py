"""License and content compliance management."""

from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set

import structlog

logger = structlog.get_logger()


class ContentLicense(Enum):
    """Common content licenses."""
    
    PUBLIC_DOMAIN = "public_domain"
    CC0 = "cc0"
    CC_BY = "cc_by"
    CC_BY_SA = "cc_by_sa"
    CC_BY_NC = "cc_by_nc"
    CC_BY_NC_SA = "cc_by_nc_sa"
    CC_BY_ND = "cc_by_nd"
    CC_BY_NC_ND = "cc_by_nc_nd"
    ALL_RIGHTS_RESERVED = "all_rights_reserved"
    UNKNOWN = "unknown"


class LicenseManager:
    """Manage content licenses and domain compliance."""
    
    def __init__(
        self,
        allowlist_path: Optional[str] = None,
        blocklist_path: Optional[str] = None
    ):
        """Initialize license manager.
        
        Args:
            allowlist_path: Path to domain allowlist
            blocklist_path: Path to domain blocklist
        """
        self.allowed_domains: Set[str] = set()
        self.blocked_domains: Set[str] = set()
        self.domain_licenses: Dict[str, str] = {}
        
        if allowlist_path:
            self._load_allowlist(allowlist_path)
        
        if blocklist_path:
            self._load_blocklist(blocklist_path)
    
    def _load_allowlist(self, filepath: str) -> None:
        """Load allowed domains from file.
        
        Args:
            filepath: Path to allowlist file
        """
        path = Path(filepath)
        if path.exists():
            try:
                with open(path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            # Format: domain [license]
                            parts = line.split(maxsplit=1)
                            domain = parts[0].lower()
                            
                            self.allowed_domains.add(domain)
                            
                            # Optional license specification
                            if len(parts) > 1:
                                self.domain_licenses[domain] = parts[1]
                
                logger.info(f"Loaded {len(self.allowed_domains)} allowed domains")
            except Exception as e:
                logger.error(f"Failed to load allowlist: {e}")
    
    def _load_blocklist(self, filepath: str) -> None:
        """Load blocked domains from file.
        
        Args:
            filepath: Path to blocklist file
        """
        path = Path(filepath)
        if path.exists():
            try:
                with open(path, 'r') as f:
                    for line in f:
                        domain = line.strip().lower()
                        if domain and not domain.startswith('#'):
                            self.blocked_domains.add(domain)
                
                logger.info(f"Loaded {len(self.blocked_domains)} blocked domains")
            except Exception as e:
                logger.error(f"Failed to load blocklist: {e}")
    
    def is_domain_allowed(self, domain: str) -> bool:
        """Check if domain is allowed for crawling.
        
        Args:
            domain: Domain to check
        
        Returns:
            True if allowed
        """
        domain = domain.lower()
        
        # Check blocklist first
        if domain in self.blocked_domains:
            return False
        
        # Check if domain or parent domain is blocked
        for blocked in self.blocked_domains:
            if domain.endswith('.' + blocked) or domain == blocked:
                return False
        
        # If allowlist exists, domain must be in it
        if self.allowed_domains:
            # Check if domain or parent domain is allowed
            for allowed in self.allowed_domains:
                if domain.endswith('.' + allowed) or domain == allowed:
                    return True
            return False
        
        # No allowlist means all non-blocked domains are allowed
        return True
    
    def get_domain_license(self, domain: str) -> str:
        """Get license for a domain.
        
        Args:
            domain: Domain to check
        
        Returns:
            License string or 'unknown'
        """
        domain = domain.lower()
        
        # Check exact match
        if domain in self.domain_licenses:
            return self.domain_licenses[domain]
        
        # Check parent domains
        for licensed_domain, license_str in self.domain_licenses.items():
            if domain.endswith('.' + licensed_domain):
                return license_str
        
        return ContentLicense.UNKNOWN.value
    
    def detect_license_from_text(self, text: str) -> str:
        """Detect license from text content.
        
        Args:
            text: Text to analyze
        
        Returns:
            Detected license or 'unknown'
        """
        if not text:
            return ContentLicense.UNKNOWN.value
        
        text_lower = text.lower()
        
        # Check for Creative Commons licenses
        if 'creative commons' in text_lower or 'cc by' in text_lower:
            if 'cc0' in text_lower or 'cc zero' in text_lower:
                return ContentLicense.CC0.value
            elif 'cc by-sa' in text_lower or 'attribution-sharealike' in text_lower:
                return ContentLicense.CC_BY_SA.value
            elif 'cc by-nc-sa' in text_lower:
                return ContentLicense.CC_BY_NC_SA.value
            elif 'cc by-nc-nd' in text_lower:
                return ContentLicense.CC_BY_NC_ND.value
            elif 'cc by-nc' in text_lower or 'noncommercial' in text_lower:
                return ContentLicense.CC_BY_NC.value
            elif 'cc by-nd' in text_lower or 'noderivatives' in text_lower:
                return ContentLicense.CC_BY_ND.value
            elif 'cc by' in text_lower:
                return ContentLicense.CC_BY.value
        
        # Check for public domain
        if 'public domain' in text_lower:
            return ContentLicense.PUBLIC_DOMAIN.value
        
        # Check for all rights reserved
        if 'all rights reserved' in text_lower or '©' in text or 'copyright' in text_lower:
            return ContentLicense.ALL_RIGHTS_RESERVED.value
        
        return ContentLicense.UNKNOWN.value
    
    def is_license_compatible(self, license: str) -> bool:
        """Check if license allows indexing.
        
        Args:
            license: License to check
        
        Returns:
            True if compatible with indexing
        """
        # For search engine indexing, most licenses are compatible
        # except those that explicitly forbid it
        incompatible = {
            ContentLicense.ALL_RIGHTS_RESERVED.value,
            # Add other incompatible licenses if needed
        }
        
        return license not in incompatible
    
    def add_allowed_domain(self, domain: str, license: Optional[str] = None) -> None:
        """Add domain to allowlist.
        
        Args:
            domain: Domain to allow
            license: Optional license for domain
        """
        domain = domain.lower()
        self.allowed_domains.add(domain)
        
        if license:
            self.domain_licenses[domain] = license
        
        logger.info(f"Added allowed domain: {domain}")
    
    def add_blocked_domain(self, domain: str) -> None:
        """Add domain to blocklist.
        
        Args:
            domain: Domain to block
        """
        domain = domain.lower()
        self.blocked_domains.add(domain)
        
        # Remove from allowlist if present
        self.allowed_domains.discard(domain)
        
        logger.info(f"Added blocked domain: {domain}")
    
    def save_lists(
        self,
        allowlist_path: Optional[str] = None,
        blocklist_path: Optional[str] = None
    ) -> None:
        """Save domain lists to files.
        
        Args:
            allowlist_path: Path for allowlist
            blocklist_path: Path for blocklist
        """
        if allowlist_path:
            try:
                with open(allowlist_path, 'w') as f:
                    f.write("# Allowed domains for crawling\n")
                    f.write("# Format: domain [license]\n\n")
                    
                    for domain in sorted(self.allowed_domains):
                        if domain in self.domain_licenses:
                            f.write(f"{domain} {self.domain_licenses[domain]}\n")
                        else:
                            f.write(f"{domain}\n")
                
                logger.info(f"Saved allowlist to {allowlist_path}")
            except Exception as e:
                logger.error(f"Failed to save allowlist: {e}")
        
        if blocklist_path:
            try:
                with open(blocklist_path, 'w') as f:
                    f.write("# Blocked domains\n\n")
                    
                    for domain in sorted(self.blocked_domains):
                        f.write(f"{domain}\n")
                
                logger.info(f"Saved blocklist to {blocklist_path}")
            except Exception as e:
                logger.error(f"Failed to save blocklist: {e}")