"""MCP tools for the model open in Catia Magic Systems of Systems Architect.

Hand-written (not auto-generated) so the LLM sees a small, well-described
tool set. Every tool is a thin wrapper over one bridge action.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from pydantic import Field

from app.bridge import call
from app.config import SETTINGS

READ = {"readOnlyHint": True, "openWorldHint": False}
WRITE = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}
DESTRUCTIVE = {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False}

ElementId = Annotated[str | None, Field(description="Element ID (from search/get results).")]
QualifiedName = Annotated[
    str | None, Field(description="Alternative to the ID: qualified name such as 'Model::Logical::Radar'.")
]
Tags = Annotated[
    dict[str, Any] | None,
    Field(
        description=(
            "Tagged values of applied stereotypes, e.g. {\"Text\": \"The system shall...\", \"Id\": \"R-12\"}. "
            "Use 'Stereotype.tag' to disambiguate. For element-valued tags pass {\"id\": \"<element id>\"}."
        )
    ),
]


def register(mcp: FastMCP) -> None:
    # ------------------------------------------------------------------ reads

    @mcp.tool(annotations=READ)
    async def get_project() -> dict:
        """Open project in Catia Magic: name, file, whether it's a server project,
        the root model, its top-level packages, and the profiles in use (SysML, UAF, ...).
        Call this first to orient yourself."""
        return await call("project")

    @mcp.tool(annotations=READ)
    async def get_element(id: ElementId = None, qualified_name: QualifiedName = None) -> dict:
        """Full details of one element: name, type, stereotypes, documentation,
        tagged values, attributes/parts/ports (for blocks), up to 200 children,
        and incoming/outgoing relationships."""
        return await call("get_element", {"id": id, "qualifiedName": qualified_name})

    @mcp.tool(annotations=READ)
    async def list_children(
        id: ElementId = None,
        qualified_name: QualifiedName = None,
        limit: Annotated[int, Field(ge=1, le=5000)] = 500,
    ) -> list[dict]:
        """Direct children of an element (the containment tree). Omit id and
        qualified_name to list the root model's children."""
        return await call("children", {"id": id, "qualifiedName": qualified_name, "limit": limit})

    @mcp.tool(annotations=READ)
    async def search_elements(
        name: Annotated[str | None, Field(description="Name contains this text (case-insensitive).")] = None,
        type: Annotated[
            str | None,
            Field(description="UML metaclass or displayed type, e.g. 'Class', 'Package', 'Activity', 'Block', 'Requirement'."),
        ] = None,
        stereotype: Annotated[
            str | None,
            Field(description="Applied stereotype name, e.g. 'Block', 'Requirement', or a UAF one like 'Capability', 'OperationalPerformer', 'ResourceArchitecture'."),
        ] = None,
        exact: Annotated[bool, Field(description="Match the name exactly instead of 'contains'.")] = False,
        scope_id: Annotated[str | None, Field(description="Only search under this element.")] = None,
        limit: Annotated[int, Field(ge=1, le=5000)] = 100,
    ) -> dict:
        """Find elements by name, type and/or stereotype anywhere in the model
        (or under scope_id). Give at least one filter."""
        return await call(
            "search",
            {"name": name, "type": type, "stereotype": stereotype, "exact": exact, "scopeId": scope_id, "limit": limit},
        )

    @mcp.tool(annotations=READ)
    async def get_relationships(id: ElementId = None, qualified_name: QualifiedName = None) -> list[dict]:
        """Incoming and outgoing directed relationships of an element (satisfy,
        deriveReqt, refine, trace, allocate, generalization, UAF dependencies...)."""
        return await call("relationships", {"id": id, "qualifiedName": qualified_name})

    @mcp.tool(annotations=READ)
    async def list_diagrams(
        name: Annotated[str | None, Field(description="Diagram name contains this text.")] = None,
    ) -> list[dict]:
        """Diagrams in the project with their type and owning element."""
        return await call("diagrams", {"name": name})

    @mcp.tool(annotations=READ)
    async def list_stereotypes(
        name: Annotated[str | None, Field(description="Stereotype name contains this text.")] = None,
        profile: Annotated[str | None, Field(description="Profile name contains this text, e.g. 'UAF', 'SysML'.")] = None,
        limit: Annotated[int, Field(ge=1, le=5000)] = 200,
    ) -> list[dict]:
        """Stereotypes available in the project, with their profile and the UML
        metaclasses they extend. Use it to find the right UAF/SysML stereotype
        and the metaclass to create it on."""
        return await call("stereotypes", {"name": name, "profile": profile, "limit": limit})

    @mcp.tool(annotations=READ)
    async def open_diagram(id: Annotated[str, Field(description="Diagram element ID from list_diagrams.")]) -> dict:
        """Open a diagram in the Catia Magic window so the user can see it."""
        return await call("open_diagram", {"id": id})

    if SETTINGS.read_only:
        return

    # ------------------------------------------------------------------ edits
    # Each edit is one undoable step in Catia Magic (Edit > Undo "MCP: ...").

    @mcp.tool(annotations=WRITE)
    async def create_element(
        type: Annotated[
            str,
            Field(
                description=(
                    "Block, Requirement, InterfaceBlock, ConstraintBlock, ValueType, Package, "
                    "or any UML metaclass (Class, Activity, Actor, UseCase, StateMachine, Interface, "
                    "Signal, DataType, Enumeration, InstanceSpecification, ...). For UAF elements give "
                    "the metaclass here and the UAF stereotype in 'stereotype' (see list_stereotypes)."
                )
            ),
        ],
        name: str | None = None,
        parent_id: Annotated[str | None, Field(description="Owner element ID. Defaults to the root model.")] = None,
        parent_qualified_name: Annotated[str | None, Field(description="Owner by qualified name.")] = None,
        stereotype: Annotated[str | None, Field(description="Extra stereotype to apply, e.g. a UAF one.")] = None,
        profile: Annotated[str | None, Field(description="Profile of the stereotype, if the name is ambiguous.")] = None,
        documentation: str | None = None,
        tags: Tags = None,
    ) -> dict:
        """Create a model element under a parent."""
        return await call(
            "create_element",
            {
                "type": type,
                "name": name,
                "parentId": parent_id,
                "parentQualifiedName": parent_qualified_name,
                "stereotype": stereotype,
                "profile": profile,
                "documentation": documentation,
                "tags": tags,
            },
        )

    @mcp.tool(annotations=WRITE)
    async def add_property(
        owner_id: Annotated[str, Field(description="Block/class that gets the property.")],
        name: str,
        kind: Annotated[
            Literal["part", "reference", "value", "port"],
            Field(description="part = composite part property, reference = shared reference, value = value property, port = proxy port."),
        ] = "part",
        type_id: Annotated[str | None, Field(description="Type of the property (a Block, ValueType, InterfaceBlock...).")] = None,
        stereotype: str | None = None,
        profile: str | None = None,
    ) -> dict:
        """Add a part, reference, value property or port to a block."""
        return await call(
            "add_property",
            {"ownerId": owner_id, "name": name, "kind": kind, "typeId": type_id, "stereotype": stereotype, "profile": profile},
        )

    @mcp.tool(annotations=WRITE)
    async def update_element(
        id: Annotated[str, Field(description="Element to change.")],
        name: str | None = None,
        documentation: str | None = None,
        type_id: Annotated[str | None, Field(description="New type (properties only).")] = None,
        owner_id: Annotated[str | None, Field(description="Move the element under this owner.")] = None,
        tags: Tags = None,
    ) -> dict:
        """Rename, re-document, retype, move, or set tagged values on an element.
        Only the fields you pass are changed."""
        return await call(
            "update_element",
            {"id": id, "name": name, "documentation": documentation, "typeId": type_id, "ownerId": owner_id, "tags": tags},
        )

    @mcp.tool(annotations=WRITE)
    async def apply_stereotype(
        id: str,
        stereotype: str,
        profile: str | None = None,
        remove: Annotated[bool, Field(description="Remove the stereotype instead of applying it.")] = False,
    ) -> dict:
        """Apply (or remove) a stereotype on an existing element."""
        return await call("apply_stereotype", {"id": id, "stereotype": stereotype, "profile": profile, "remove": remove})

    @mcp.tool(annotations=WRITE)
    async def create_relationship(
        type: Annotated[
            str,
            Field(
                description=(
                    "Satisfy, DeriveReqt, Refine, Trace, Verify, Copy, Allocate, Generalization, "
                    "Dependency, Abstraction, Usage, Realization. For UAF relationships use Dependency "
                    "or Abstraction plus the UAF stereotype."
                )
            ),
        ],
        source_id: Annotated[str, Field(description="Client/source end (for Satisfy: the design element; for Generalization: the specific one).")],
        target_id: Annotated[str, Field(description="Supplier/target end (for Satisfy: the requirement; for Generalization: the general one).")],
        name: str | None = None,
        stereotype: str | None = None,
        profile: str | None = None,
    ) -> dict:
        """Create a directed relationship between two elements."""
        return await call(
            "create_relationship",
            {"type": type, "sourceId": source_id, "targetId": target_id, "name": name, "stereotype": stereotype, "profile": profile},
        )

    @mcp.tool(annotations=WRITE)
    async def save_project() -> dict:
        """Save a local (.mdzip) project. Server projects (Teamwork Cloud /
        3DEXPERIENCE) must be committed from Catia Magic by the user."""
        return await call("save_project")

    if SETTINGS.allow_delete:

        @mcp.tool(annotations=DESTRUCTIVE)
        async def delete_element(id: Annotated[str, Field(description="Element to delete, with everything it owns.")]) -> dict:
            """Delete an element and everything it owns. Confirm with the user
            first. It can be undone in Catia Magic with Edit > Undo."""
            return await call("delete_element", {"id": id})
