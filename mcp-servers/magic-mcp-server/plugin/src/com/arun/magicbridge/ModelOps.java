package com.arun.magicbridge;

import com.nomagic.magicdraw.core.Application;
import com.nomagic.magicdraw.core.Project;
import com.nomagic.magicdraw.core.ProjectUtilities;
import com.nomagic.magicdraw.core.project.ProjectDescriptor;
import com.nomagic.magicdraw.core.project.ProjectDescriptorsFactory;
import com.nomagic.magicdraw.openapi.uml.ModelElementsManager;
import com.nomagic.magicdraw.openapi.uml.SessionManager;
import com.nomagic.magicdraw.uml.BaseElement;
import com.nomagic.magicdraw.uml.symbols.DiagramPresentationElement;
import com.nomagic.uml2.ext.jmi.helpers.CoreHelper;
import com.nomagic.uml2.ext.jmi.helpers.StereotypesHelper;
import com.nomagic.uml2.ext.magicdraw.classes.mdkernel.AggregationKindEnum;
import com.nomagic.uml2.ext.magicdraw.classes.mdkernel.Classifier;
import com.nomagic.uml2.ext.magicdraw.classes.mdkernel.DirectedRelationship;
import com.nomagic.uml2.ext.magicdraw.classes.mdkernel.Element;
import com.nomagic.uml2.ext.magicdraw.classes.mdkernel.Generalization;
import com.nomagic.uml2.ext.magicdraw.classes.mdkernel.NamedElement;
import com.nomagic.uml2.ext.magicdraw.classes.mdkernel.Package;
import com.nomagic.uml2.ext.magicdraw.classes.mdkernel.Property;
import com.nomagic.uml2.ext.magicdraw.classes.mdkernel.Type;
import com.nomagic.uml2.ext.magicdraw.mdprofiles.Profile;
import com.nomagic.uml2.ext.magicdraw.mdprofiles.Stereotype;
import com.nomagic.uml2.impl.ElementsFactory;

import java.lang.reflect.Method;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Deque;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * The model operations behind each /api/&lt;action&gt; endpoint.
 * Every method runs on the Swing event thread (BridgeServer guarantees it).
 */
public class ModelOps {

    private static final int MAX_VISIT = 500_000;

    /**
     * Friendly type names -> UML metaclass + stereotype. Anything not listed
     * is treated as a raw UML metaclass name (Class, Package, Activity, ...),
     * and any stereotype (SysML, UAF, custom) can be given separately.
     */
    private static final Map<String, String[]> TYPE_ALIASES = new LinkedHashMap<String, String[]>();
    static {
        TYPE_ALIASES.put("block", new String[]{"Class", "Block"});
        TYPE_ALIASES.put("requirement", new String[]{"Class", "Requirement"});
        TYPE_ALIASES.put("interfaceblock", new String[]{"Class", "InterfaceBlock"});
        TYPE_ALIASES.put("constraintblock", new String[]{"Class", "ConstraintBlock"});
        TYPE_ALIASES.put("valuetype", new String[]{"DataType", "ValueType"});
        TYPE_ALIASES.put("package", new String[]{"Package", null});
        TYPE_ALIASES.put("model", new String[]{"Model", null});
        TYPE_ALIASES.put("comment", new String[]{"Comment", null});
    }

    /** Relationship names -> UML metaclass + stereotype. */
    private static final Map<String, String[]> REL_ALIASES = new LinkedHashMap<String, String[]>();
    static {
        REL_ALIASES.put("dependency", new String[]{"Dependency", null});
        REL_ALIASES.put("abstraction", new String[]{"Abstraction", null});
        REL_ALIASES.put("usage", new String[]{"Usage", null});
        REL_ALIASES.put("realization", new String[]{"Realization", null});
        REL_ALIASES.put("satisfy", new String[]{"Abstraction", "Satisfy"});
        REL_ALIASES.put("derivereqt", new String[]{"Abstraction", "DeriveReqt"});
        REL_ALIASES.put("refine", new String[]{"Abstraction", "Refine"});
        REL_ALIASES.put("trace", new String[]{"Abstraction", "Trace"});
        REL_ALIASES.put("verify", new String[]{"Abstraction", "Verify"});
        REL_ALIASES.put("copy", new String[]{"Abstraction", "Copy"});
        REL_ALIASES.put("allocate", new String[]{"Abstraction", "Allocate"});
        REL_ALIASES.put("generalization", new String[]{"Generalization", null});
    }

    // ------------------------------------------------------------------
    // dispatch

    public Object dispatch(String action, Map<String, Object> a) throws Exception {
        if ("project".equals(action)) return project();
        if ("get_element".equals(action)) return getElement(a);
        if ("children".equals(action)) return children(a);
        if ("search".equals(action)) return search(a);
        if ("relationships".equals(action)) return relationships(a);
        if ("diagrams".equals(action)) return diagrams(a);
        if ("stereotypes".equals(action)) return stereotypes(a);
        if ("create_element".equals(action)) return createElement(a);
        if ("add_property".equals(action)) return addProperty(a);
        if ("update_element".equals(action)) return updateElement(a);
        if ("apply_stereotype".equals(action)) return applyStereotype(a);
        if ("create_relationship".equals(action)) return createRelationship(a);
        if ("delete_element".equals(action)) return deleteElement(a);
        if ("open_diagram".equals(action)) return openDiagram(a);
        if ("save_project".equals(action)) return saveProject();
        throw new BridgeException(404, "Unknown action: " + action);
    }

    // ------------------------------------------------------------------
    // reads

    private Map<String, Object> project() throws BridgeException {
        Project p = requireProject();
        Map<String, Object> m = new LinkedHashMap<String, Object>();
        m.put("name", p.getName());
        m.put("file", p.getFileName());
        m.put("remote", ProjectUtilities.isRemote(p.getPrimaryProject()));
        m.put("primaryModel", summary(p.getPrimaryModel()));
        List<Object> top = new ArrayList<Object>();
        for (Element e : p.getPrimaryModel().getOwnedElement()) top.add(summary(e));
        m.put("topLevel", top);
        List<Object> profiles = new ArrayList<Object>();
        for (Profile pr : StereotypesHelper.getAllProfiles(p)) profiles.add(pr.getName());
        m.put("profiles", profiles);
        return m;
    }

    private Map<String, Object> getElement(Map<String, Object> a) throws BridgeException {
        Element e = resolve(a, "id");
        Map<String, Object> m = summary(e);
        m.put("documentation", CoreHelper.getComment(e));
        m.put("taggedValues", taggedValues(e));
        if (e instanceof Classifier) {
            List<Object> props = new ArrayList<Object>();
            for (Property p : ((Classifier) e).getAttribute()) props.add(propertySummary(p));
            m.put("attributes", props);
        }
        if (e instanceof Property) m.putAll(propertySummary((Property) e));
        List<Object> kids = new ArrayList<Object>();
        int n = 0;
        for (Element c : e.getOwnedElement()) {
            if (n++ >= 200) break;
            kids.add(summary(c));
        }
        m.put("children", kids);
        m.put("relationships", relationshipList(e));
        return m;
    }

    private List<Object> children(Map<String, Object> a) throws BridgeException {
        Element e = a.get("id") == null && a.get("qualifiedName") == null
                ? requireProject().getPrimaryModel() : resolve(a, "id");
        int limit = intArg(a, "limit", 500);
        List<Object> out = new ArrayList<Object>();
        for (Element c : e.getOwnedElement()) {
            if (out.size() >= limit) break;
            out.add(summary(c));
        }
        return out;
    }

    private Map<String, Object> search(Map<String, Object> a) throws BridgeException {
        Project p = requireProject();
        String name = lower(str(a, "name"));
        boolean exact = Boolean.TRUE.equals(a.get("exact"));
        String type = lower(str(a, "type"));
        String stereo = lower(str(a, "stereotype"));
        int limit = intArg(a, "limit", 100);
        Element root = a.get("scopeId") != null ? resolve(a, "scopeId") : p.getPrimaryModel();

        List<Object> hits = new ArrayList<Object>();
        int visited = 0;
        boolean truncated = false;
        Deque<Element> stack = new ArrayDeque<Element>();
        stack.push(root);
        while (!stack.isEmpty()) {
            Element e = stack.pop();
            if (++visited > MAX_VISIT) { truncated = true; break; }
            if (matches(e, name, exact, type, stereo)) {
                if (hits.size() >= limit) { truncated = true; break; }
                hits.add(summary(e));
            }
            for (Element c : e.getOwnedElement()) stack.push(c);
        }
        Map<String, Object> m = new LinkedHashMap<String, Object>();
        m.put("count", hits.size());
        m.put("truncated", truncated);
        m.put("results", hits);
        return m;
    }

    private boolean matches(Element e, String name, boolean exact, String type, String stereo) {
        if (name != null) {
            if (!(e instanceof NamedElement)) return false;
            String n = lower(((NamedElement) e).getName());
            if (n == null) return false;
            if (exact ? !n.equals(name) : !n.contains(name)) return false;
        }
        if (type != null) {
            String meta = lower(metaclass(e));
            String human = lower(e.getHumanType());
            if (!type.equals(meta) && !type.equals(human)) return false;
        }
        if (stereo != null) {
            boolean found = false;
            for (Stereotype s : StereotypesHelper.getStereotypes(e)) {
                if (stereo.equals(lower(s.getName()))) { found = true; break; }
            }
            if (!found) return false;
        }
        return true;
    }

    private List<Object> relationships(Map<String, Object> a) throws BridgeException {
        return relationshipList(resolve(a, "id"));
    }

    private List<Object> relationshipList(Element e) {
        List<Object> out = new ArrayList<Object>();
        for (DirectedRelationship r : e.get_directedRelationshipOfSource()) out.add(relSummary(r, "outgoing"));
        for (DirectedRelationship r : e.get_directedRelationshipOfTarget()) out.add(relSummary(r, "incoming"));
        return out;
    }

    private Map<String, Object> relSummary(DirectedRelationship r, String direction) {
        Map<String, Object> m = summary(r);
        m.put("direction", direction);
        List<Object> src = new ArrayList<Object>();
        for (Element s : r.getSource()) src.add(ref(s));
        List<Object> tgt = new ArrayList<Object>();
        for (Element t : r.getTarget()) tgt.add(ref(t));
        m.put("sources", src);
        m.put("targets", tgt);
        return m;
    }

    private List<Object> diagrams(Map<String, Object> a) throws BridgeException {
        Project p = requireProject();
        String name = lower(str(a, "name"));
        List<Object> out = new ArrayList<Object>();
        for (DiagramPresentationElement d : p.getDiagrams()) {
            String n = d.getDiagram().getName();
            if (name != null && (n == null || !n.toLowerCase(Locale.ROOT).contains(name))) continue;
            Map<String, Object> m = new LinkedHashMap<String, Object>();
            m.put("id", d.getDiagram().getID());
            m.put("name", n);
            m.put("diagramType", d.getDiagramType() != null ? d.getDiagramType().getType() : null);
            Element owner = d.getDiagram().getOwner();
            m.put("owner", owner != null ? ref(owner) : null);
            out.add(m);
        }
        return out;
    }

    /** Stereotypes available in the project, optionally filtered by name or profile. */
    private List<Object> stereotypes(Map<String, Object> a) throws BridgeException {
        Project p = requireProject();
        String name = lower(str(a, "name"));
        String profile = lower(str(a, "profile"));
        int limit = intArg(a, "limit", 200);
        List<Object> out = new ArrayList<Object>();
        for (Stereotype s : StereotypesHelper.getAllStereotypes(p)) {
            String sn = lower(s.getName());
            if (name != null && (sn == null || !sn.contains(name))) continue;
            Package pr = StereotypesHelper.getProfileForStereotype(s);
            String pn = pr != null ? pr.getName() : null;
            if (profile != null && (pn == null || !pn.toLowerCase(Locale.ROOT).contains(profile))) continue;
            Map<String, Object> m = new LinkedHashMap<String, Object>();
            m.put("name", s.getName());
            m.put("profile", pn);
            List<Object> metas = new ArrayList<Object>();
            for (com.nomagic.uml2.ext.magicdraw.classes.mdkernel.Class mc : StereotypesHelper.getBaseClasses(s)) {
                metas.add(mc.getName());
            }
            m.put("metaclasses", metas);
            out.add(m);
            if (out.size() >= limit) break;
        }
        return out;
    }

    // ------------------------------------------------------------------
    // edits

    private Map<String, Object> createElement(final Map<String, Object> a) throws Exception {
        final Project p = requireProject();
        final Element parent = a.get("parentId") == null && a.get("parentQualifiedName") == null
                ? p.getPrimaryModel() : resolveAny(a, "parentId", "parentQualifiedName");
        String type = requireStr(a, "type");
        String[] alias = TYPE_ALIASES.get(type.toLowerCase(Locale.ROOT).replace(" ", ""));
        final String metaclass = alias != null ? alias[0] : type;
        final String aliasStereo = alias != null ? alias[1] : null;

        return inSession(p, "MCP: create " + type, new Op() {
            public Map<String, Object> run() throws Exception {
                SessionManager.getInstance().checkReadOnly(parent);
                Element e = instantiate(p.getElementsFactory(), metaclass);
                String name = str(a, "name");
                if (name != null && e instanceof NamedElement) ((NamedElement) e).setName(name);
                ModelElementsManager.getInstance().addElement(e, parent);
                if (aliasStereo != null) apply(p, e, aliasStereo, null);
                String st = str(a, "stereotype");
                if (st != null) apply(p, e, st, str(a, "profile"));
                String doc = str(a, "documentation");
                if (doc != null) CoreHelper.setComment(e, doc);
                setTags(p, e, a.get("tags"));
                return summary(e);
            }
        });
    }

    private Map<String, Object> addProperty(final Map<String, Object> a) throws Exception {
        final Project p = requireProject();
        final Element owner = resolveAny(a, "ownerId", "ownerQualifiedName");
        if (!(owner instanceof Classifier)) throw new BridgeException("Owner must be a classifier (e.g. a Block)");
        final Element type = a.get("typeId") != null || a.get("typeQualifiedName") != null
                ? resolveAny(a, "typeId", "typeQualifiedName") : null;
        if (type != null && !(type instanceof Type)) throw new BridgeException("typeId must point to a type (Block, ValueType, ...)");
        final String kind = lower(str(a, "kind")); // part | reference | value | port | null

        return inSession(p, "MCP: add property", new Op() {
            public Map<String, Object> run() throws Exception {
                SessionManager.getInstance().checkReadOnly(owner);
                ElementsFactory f = p.getElementsFactory();
                Property prop = "port".equals(kind) ? f.createPortInstance() : f.createPropertyInstance();
                prop.setName(requireStr(a, "name"));
                if (type != null) prop.setType((Type) type);
                if ("part".equals(kind)) prop.setAggregation(AggregationKindEnum.COMPOSITE);
                ModelElementsManager.getInstance().addElement(prop, owner);
                if ("port".equals(kind)) {
                    // SysML proxy port when SysML is loaded; plain UML port otherwise.
                    Stereotype s = findStereotype(p, "ProxyPort", null);
                    if (s != null && StereotypesHelper.canApplyStereotype(prop, s)) StereotypesHelper.addStereotype(prop, s);
                }
                String st = str(a, "stereotype");
                if (st != null) apply(p, prop, st, str(a, "profile"));
                return propertySummary(prop);
            }
        });
    }

    private Map<String, Object> updateElement(final Map<String, Object> a) throws Exception {
        final Project p = requireProject();
        final Element e = resolve(a, "id");
        return inSession(p, "MCP: update element", new Op() {
            public Map<String, Object> run() throws Exception {
                SessionManager.getInstance().checkReadOnly(e);
                if (a.containsKey("name")) {
                    if (!(e instanceof NamedElement)) throw new BridgeException("Element has no name");
                    ((NamedElement) e).setName(str(a, "name"));
                }
                if (a.containsKey("documentation")) CoreHelper.setComment(e, str(a, "documentation"));
                if (a.containsKey("typeId")) {
                    if (!(e instanceof Property)) throw new BridgeException("Only properties have a type");
                    Element t = resolve(a, "typeId");
                    if (!(t instanceof Type)) throw new BridgeException("typeId is not a type");
                    ((Property) e).setType((Type) t);
                }
                if (a.containsKey("ownerId")) {
                    Element newOwner = resolve(a, "ownerId");
                    SessionManager.getInstance().checkReadOnly(newOwner);
                    ModelElementsManager.getInstance().moveElement(e, newOwner);
                }
                setTags(p, e, a.get("tags"));
                return summary(e);
            }
        });
    }

    private Map<String, Object> applyStereotype(final Map<String, Object> a) throws Exception {
        final Project p = requireProject();
        final Element e = resolve(a, "id");
        final boolean remove = Boolean.TRUE.equals(a.get("remove"));
        return inSession(p, "MCP: stereotype", new Op() {
            public Map<String, Object> run() throws Exception {
                SessionManager.getInstance().checkReadOnly(e);
                String name = requireStr(a, "stereotype");
                if (remove) {
                    Stereotype s = findStereotype(p, name, str(a, "profile"));
                    if (s == null) throw new BridgeException("Stereotype not found: " + name);
                    StereotypesHelper.removeStereotype(e, s);
                } else {
                    apply(p, e, name, str(a, "profile"));
                }
                return summary(e);
            }
        });
    }

    private Map<String, Object> createRelationship(final Map<String, Object> a) throws Exception {
        final Project p = requireProject();
        final Element src = resolveAny(a, "sourceId", "sourceQualifiedName");
        final Element tgt = resolveAny(a, "targetId", "targetQualifiedName");
        String type = requireStr(a, "type");
        String[] alias = REL_ALIASES.get(type.toLowerCase(Locale.ROOT).replace(" ", ""));
        final String metaclass = alias != null ? alias[0] : type;
        final String aliasStereo = alias != null ? alias[1] : null;

        return inSession(p, "MCP: relate " + type, new Op() {
            public Map<String, Object> run() throws Exception {
                Element rel;
                if ("Generalization".equals(metaclass)) {
                    if (!(src instanceof Classifier) || !(tgt instanceof Classifier)) {
                        throw new BridgeException("Generalization needs two classifiers (specific = source, general = target)");
                    }
                    SessionManager.getInstance().checkReadOnly(src);
                    Generalization g = p.getElementsFactory().createGeneralizationInstance();
                    g.setGeneral((Classifier) tgt);
                    g.setSpecific((Classifier) src);
                    ModelElementsManager.getInstance().addElement(g, src);
                    rel = g;
                } else {
                    Element owner = nearestPackage(src);
                    SessionManager.getInstance().checkReadOnly(owner);
                    rel = instantiate(p.getElementsFactory(), metaclass);
                    CoreHelper.setClientElement(rel, src);
                    CoreHelper.setSupplierElement(rel, tgt);
                    ModelElementsManager.getInstance().addElement(rel, owner);
                }
                String name = str(a, "name");
                if (name != null && rel instanceof NamedElement) ((NamedElement) rel).setName(name);
                if (aliasStereo != null) apply(p, rel, aliasStereo, null);
                String st = str(a, "stereotype");
                if (st != null) apply(p, rel, st, str(a, "profile"));
                return relSummary((DirectedRelationship) rel, "outgoing");
            }
        });
    }

    private Map<String, Object> deleteElement(Map<String, Object> a) throws Exception {
        final Project p = requireProject();
        final Element e = resolve(a, "id");
        if (e == p.getPrimaryModel()) throw new BridgeException("Refusing to delete the root model");
        final Map<String, Object> before = summary(e);
        return inSession(p, "MCP: delete element", new Op() {
            public Map<String, Object> run() throws Exception {
                SessionManager.getInstance().checkReadOnly(e);
                ModelElementsManager.getInstance().removeElement(e);
                Map<String, Object> m = new LinkedHashMap<String, Object>();
                m.put("deleted", before);
                return m;
            }
        });
    }

    private Map<String, Object> openDiagram(Map<String, Object> a) throws BridgeException {
        Project p = requireProject();
        Element e = resolve(a, "id");
        DiagramPresentationElement dpe = null;
        for (DiagramPresentationElement d : p.getDiagrams()) {
            if (d.getDiagram() == e) { dpe = d; break; }
        }
        if (dpe == null) throw new BridgeException("Not a diagram: " + a.get("id"));
        dpe.open();
        Map<String, Object> m = new LinkedHashMap<String, Object>();
        m.put("opened", dpe.getDiagram().getName());
        return m;
    }

    private Map<String, Object> saveProject() throws BridgeException {
        Project p = requireProject();
        if (ProjectUtilities.isRemote(p.getPrimaryProject())) {
            throw new BridgeException(409, "This is a server (Teamwork Cloud / 3DEXPERIENCE) project. Commit it from Catia Magic instead.");
        }
        ProjectDescriptor d = ProjectDescriptorsFactory.getDescriptorForProject(p);
        boolean ok = Application.getInstance().getProjectsManager().saveProject(d, true);
        Map<String, Object> m = new LinkedHashMap<String, Object>();
        m.put("saved", ok);
        m.put("file", p.getFileName());
        return m;
    }

    // ------------------------------------------------------------------
    // helpers

    private interface Op {
        Map<String, Object> run() throws Exception;
    }

    /** Runs an edit as one undoable session; rolls back if anything fails. */
    private Map<String, Object> inSession(Project p, String name, Op op) throws Exception {
        SessionManager sm = SessionManager.getInstance();
        if (sm.isSessionCreated(p)) throw new BridgeException(409, "Catia Magic is busy with another edit; try again.");
        sm.createSession(p, name);
        try {
            Map<String, Object> r = op.run();
            sm.closeSession(p);
            return r;
        } catch (Exception ex) {
            sm.cancelSession(p);
            if (ex.getClass().getSimpleName().equals("ReadOnlyElementException")) {
                throw new BridgeException(409, "Element is read-only (in a used project, or not locked on the server): " + ex.getMessage());
            }
            throw ex;
        }
    }

    private Project requireProject() throws BridgeException {
        Project p = Application.getInstance().getProject();
        if (p == null) throw new BridgeException(409, "No project is open in Catia Magic");
        return p;
    }

    private Element resolve(Map<String, Object> a, String idKey) throws BridgeException {
        String qKey = idKey.equals("id") ? "qualifiedName" : idKey.replace("Id", "QualifiedName");
        return resolveAny(a, idKey, qKey);
    }

    /** Find an element by its ID, or by its qualified name (Model::Pkg::Block). */
    private Element resolveAny(Map<String, Object> a, String idKey, String qnKey) throws BridgeException {
        Project p = requireProject();
        String id = str(a, idKey);
        if (id != null) {
            BaseElement b = p.getElementByID(id);
            if (!(b instanceof Element)) throw new BridgeException(404, "No element with id " + id);
            return (Element) b;
        }
        String qn = str(a, qnKey);
        if (qn != null) {
            Element found = byQualifiedName(p, qn);
            if (found == null) throw new BridgeException(404, "No element named " + qn);
            return found;
        }
        throw new BridgeException("Give " + idKey + " or " + qnKey);
    }

    private Element byQualifiedName(Project p, String qn) {
        Deque<Element> stack = new ArrayDeque<Element>();
        stack.push(p.getPrimaryModel());
        int visited = 0;
        while (!stack.isEmpty() && visited++ < MAX_VISIT) {
            Element e = stack.pop();
            if (e instanceof NamedElement) {
                String q = ((NamedElement) e).getQualifiedName();
                if (qn.equals(q)) return e;
                // Only descend where the path can still match.
                if (q != null && !q.isEmpty() && !qn.startsWith(q + "::") && e != p.getPrimaryModel()) continue;
            }
            for (Element c : e.getOwnedElement()) stack.push(c);
        }
        return null;
    }

    private Element instantiate(ElementsFactory f, String metaclass) throws BridgeException {
        String m = metaclass.replace(" ", "");
        try {
            Method method = f.getClass().getMethod("create" + m + "Instance");
            Object o = method.invoke(f);
            if (!(o instanceof Element)) throw new BridgeException("Not a model element type: " + metaclass);
            return (Element) o;
        } catch (NoSuchMethodException e) {
            throw new BridgeException("Unknown UML metaclass '" + metaclass
                    + "'. Use a UML metaclass (Class, Package, Activity, Actor, UseCase, ...) or Block, Requirement, InterfaceBlock, ConstraintBlock, ValueType.");
        } catch (BridgeException e) {
            throw e;
        } catch (Exception e) {
            throw new BridgeException("Could not create " + metaclass + ": " + e);
        }
    }

    private Stereotype findStereotype(Project p, String name, String profileName) {
        if (profileName != null) {
            Profile pr = StereotypesHelper.getProfile(p, profileName);
            if (pr != null) {
                Stereotype s = StereotypesHelper.getStereotype(p, name, pr);
                if (s != null) return s;
            }
        }
        // No profile given: first stereotype with that name across all profiles,
        // preferring SysML/UAF-standard ones over look-alikes in custom profiles.
        Stereotype first = null;
        for (Stereotype s : StereotypesHelper.getAllStereotypes(p)) {
            if (!name.equals(s.getName())) continue;
            if (first == null) first = s;
            com.nomagic.uml2.ext.magicdraw.classes.mdkernel.Package pr = StereotypesHelper.getProfileForStereotype(s);
            String pn = pr != null ? pr.getName() : "";
            if (pn != null && (pn.contains("SysML") || pn.contains("UAF") || pn.contains("MD Customization"))) return s;
        }
        return first;
    }

    private void apply(Project p, Element e, String stereo, String profile) throws BridgeException {
        Stereotype s = findStereotype(p, stereo, profile);
        if (s == null) {
            throw new BridgeException("Stereotype '" + stereo + "' not found. Is its profile (SysML, UAF, ...) used by this project? Try list_stereotypes.");
        }
        if (!StereotypesHelper.canApplyStereotype(e, s)) {
            throw new BridgeException("Stereotype '" + stereo + "' cannot be applied to a " + metaclass(e));
        }
        if (!StereotypesHelper.hasStereotype(e, s)) StereotypesHelper.addStereotype(e, s);
    }

    /**
     * tags: {"Text": "...", "Id": "R-1"} applies to whichever applied
     * stereotype owns the property; or {"Requirement.Text": "..."} to be explicit.
     */
    @SuppressWarnings("unchecked")
    private void setTags(Project p, Element e, Object tagsObj) throws BridgeException {
        if (!(tagsObj instanceof Map)) return;
        Map<String, Object> tags = (Map<String, Object>) tagsObj;
        for (Map.Entry<String, Object> t : tags.entrySet()) {
            String key = t.getKey();
            String stName = null;
            String prop = key;
            int dot = key.indexOf('.');
            if (dot > 0) { stName = key.substring(0, dot); prop = key.substring(dot + 1); }
            Stereotype owner = null;
            for (Stereotype s : StereotypesHelper.getStereotypes(e)) {
                if (stName != null && !stName.equals(s.getName())) continue;
                if (findTagProperty(s, prop, new HashSet<Stereotype>()) != null) { owner = s; break; }
            }
            if (owner == null) throw new BridgeException("No applied stereotype has a tag '" + key + "'");
            Object v = t.getValue();
            if (v instanceof Map && ((Map<String, Object>) v).get("id") != null) {
                BaseElement ref = p.getElementByID(String.valueOf(((Map<String, Object>) v).get("id")));
                v = ref;
            }
            StereotypesHelper.setStereotypePropertyValue(e, owner, prop, v);
        }
    }

    private Property findTagProperty(Stereotype s, String name, Set<Stereotype> seen) {
        if (!seen.add(s)) return null;
        for (Property p : s.getOwnedAttribute()) {
            if (name.equals(p.getName())) return p;
        }
        for (com.nomagic.uml2.ext.magicdraw.classes.mdkernel.Class g : s.getSuperClass()) {
            if (g instanceof Stereotype) {
                Property p = findTagProperty((Stereotype) g, name, seen);
                if (p != null) return p;
            }
        }
        return null;
    }

    private Map<String, Object> taggedValues(Element e) {
        Map<String, Object> out = new LinkedHashMap<String, Object>();
        for (Stereotype s : StereotypesHelper.getStereotypes(e)) {
            Map<String, Object> vals = new LinkedHashMap<String, Object>();
            collectTags(e, s, s, vals, new HashSet<Stereotype>());
            if (!vals.isEmpty()) out.put(s.getName(), vals);
        }
        return out;
    }

    private void collectTags(Element e, Stereotype applied, Stereotype s, Map<String, Object> vals, Set<Stereotype> seen) {
        if (!seen.add(s)) return;
        for (Property p : s.getOwnedAttribute()) {
            String n = p.getName();
            if (n == null || n.startsWith("base_") || n.startsWith("extension_")) continue;
            List<?> raw = StereotypesHelper.getStereotypePropertyValue(e, applied, n);
            if (raw == null || raw.isEmpty()) continue;
            List<Object> conv = new ArrayList<Object>();
            for (Object o : raw) conv.add(o instanceof Element ? ref((Element) o) : String.valueOf(o));
            vals.put(n, conv.size() == 1 ? conv.get(0) : conv);
        }
        for (com.nomagic.uml2.ext.magicdraw.classes.mdkernel.Class g : s.getSuperClass()) {
            if (g instanceof Stereotype) collectTags(e, applied, (Stereotype) g, vals, seen);
        }
    }

    private Element nearestPackage(Element e) {
        Element cur = e;
        while (cur != null && !(cur instanceof Package)) cur = cur.getOwner();
        return cur != null ? cur : requireProjectQuiet().getPrimaryModel();
    }

    private Project requireProjectQuiet() {
        return Application.getInstance().getProject();
    }

    private Map<String, Object> summary(Element e) {
        Map<String, Object> m = new LinkedHashMap<String, Object>();
        m.put("id", e.getID());
        if (e instanceof NamedElement) {
            m.put("name", ((NamedElement) e).getName());
            m.put("qualifiedName", ((NamedElement) e).getQualifiedName());
        }
        m.put("type", e.getHumanType());
        m.put("metaclass", metaclass(e));
        List<Object> st = new ArrayList<Object>();
        for (Stereotype s : StereotypesHelper.getStereotypes(e)) st.add(s.getName());
        if (!st.isEmpty()) m.put("stereotypes", st);
        Element owner = e.getOwner();
        if (owner != null) m.put("ownerId", owner.getID());
        Collection<Element> kids = e.getOwnedElement();
        m.put("childCount", kids.size());
        m.put("editable", ProjectUtilities.isElementInAttachedProject(e) ? Boolean.FALSE : Boolean.valueOf(e.isEditable()));
        return m;
    }

    private Map<String, Object> propertySummary(Property p) {
        Map<String, Object> m = new LinkedHashMap<String, Object>();
        m.put("id", p.getID());
        m.put("name", p.getName());
        m.put("type", p.getType() != null ? ref(p.getType()) : null);
        m.put("aggregation", p.getAggregation() != null ? p.getAggregation().toString() : null);
        m.put("kind", p.getHumanType());
        List<Object> st = new ArrayList<Object>();
        for (Stereotype s : StereotypesHelper.getStereotypes(p)) st.add(s.getName());
        if (!st.isEmpty()) m.put("stereotypes", st);
        return m;
    }

    private Map<String, Object> ref(Element e) {
        Map<String, Object> m = new LinkedHashMap<String, Object>();
        m.put("id", e.getID());
        m.put("name", e instanceof NamedElement ? ((NamedElement) e).getName() : e.getHumanName());
        m.put("type", e.getHumanType());
        return m;
    }

    private static String metaclass(Element e) {
        return e.getClassType() != null ? e.getClassType().getSimpleName() : e.getClass().getSimpleName();
    }

    private static String str(Map<String, Object> a, String k) {
        Object v = a.get(k);
        if (v == null) return null;
        String s = String.valueOf(v);
        return s.isEmpty() ? null : s;
    }

    private static String requireStr(Map<String, Object> a, String k) throws BridgeException {
        String s = str(a, k);
        if (s == null) throw new BridgeException("Missing '" + k + "'");
        return s;
    }

    private static int intArg(Map<String, Object> a, String k, int def) {
        Object v = a.get(k);
        if (v instanceof Number) return Math.max(1, Math.min(5000, ((Number) v).intValue()));
        return def;
    }

    private static String lower(String s) {
        return s == null ? null : s.toLowerCase(Locale.ROOT);
    }
}
