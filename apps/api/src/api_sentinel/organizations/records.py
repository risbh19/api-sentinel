"""Internal persistence operations for a caller with an established organization scope."""

from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from .models import Organization, Project


def create_organization(session: Session, name: str) -> Organization:
    organization = Organization(name=name)
    session.add(organization)
    session.flush()
    return organization


class OrganizationRecords:
    def __init__(self, session: Session, organization_id: UUID) -> None:
        self.session = session
        self.organization_id = organization_id

    def organization(self) -> Organization | None:
        return self.session.get(Organization, self.organization_id)

    def rename_organization(self, name: str) -> Organization | None:
        return self.session.scalar(
            update(Organization)
            .where(Organization.id == self.organization_id)
            .values(name=name)
            .returning(Organization)
        )

    def delete_organization(self) -> bool:
        return (
            self.session.scalar(
                delete(Organization)
                .where(Organization.id == self.organization_id)
                .returning(Organization.id)
            )
            is not None
        )

    def create_project(self, name: str, slug: str) -> Project:
        project = Project(organization_id=self.organization_id, name=name, slug=slug)
        self.session.add(project)
        self.session.flush()
        return project

    def project(self, project_id: UUID) -> Project | None:
        return self.session.scalar(
            select(Project).where(
                Project.organization_id == self.organization_id, Project.id == project_id
            )
        )

    def projects(self, *, limit: int = 50, after_slug: str | None = None) -> list[Project]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        query = select(Project).where(Project.organization_id == self.organization_id)
        if after_slug is not None:
            query = query.where(Project.slug > after_slug)
        return list(self.session.scalars(query.order_by(Project.slug).limit(limit)))

    def rename_project(self, project_id: UUID, name: str) -> Project | None:
        return self.session.scalar(
            update(Project)
            .where(Project.organization_id == self.organization_id, Project.id == project_id)
            .values(name=name)
            .returning(Project)
        )

    def delete_project(self, project_id: UUID) -> bool:
        return (
            self.session.scalar(
                delete(Project)
                .where(Project.organization_id == self.organization_id, Project.id == project_id)
                .returning(Project.id)
            )
            is not None
        )
