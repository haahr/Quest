# A Semantic Basis for Quest

**Luca Cardelli**  
*Digital Equipment Corporation, Systems Research Center*  

**Giuseppe Longo**  
*LIENS, Ecole Normale Supérieure, Paris*  

*Appears in: Journal of Functional Programming, Vol 1, Part 4, pp.417-458, Cambridge Univ. Press, Oct 1991.*  
*SRC Research Report 55, February 14, 1990. Revised January 1, 1993.*  
*© Digital Equipment Corporation 1990, 1993.*

---

## Abstract

Quest is a programming language based on impredicative type quantifiers and subtyping within a three-level structure of
kinds, types and type operators, and values.

The semantics of Quest is rather challenging. In particular, difficulties arise when we try to model simultaneously
features such as contravariant function spaces, record types, subtyping, recursive types, and fixpoints.

In this paper we describe in detail the type inference rules for Quest, and we give them meaning using a partial
equivalence relation model of types. Subtyping is interpreted as in previous work by Bruce and Longo, but the
interpretation of some aspects, namely subsumption, power kinds, and record subtyping, is novel. The latter is based on
a new encoding of record types.

We concentrate on modeling quantifiers and subtyping; recursion is the subject of current work.

---

## Contents

- [1. Introduction](#1-introduction)
- [2. Quest rules](#2-quest-rules)
  - [2.1. Terms](#21-terms)
  - [2.2. Judgments](#22-judgments)
  - [2.3. Environments and variables](#23-environments-and-variables)
  - [2.4. Equivalence and inclusion](#24-equivalence-and-inclusion)
  - [2.5. Subsumption vs. coercion](#25-subsumption-vs-coercion)
  - [2.6. Power kinds](#26-power-kinds)
  - [2.7. Operator kinds](#27-operator-kinds)
  - [2.8. The kind of types](#28-the-kind-of-types)
  - [2.9. Formal system](#29-formal-system)
  - [2.10. Records and other encodings](#210-records-and-other-encodings)
- [3. Semantics background](#3-semantics-background)
  - [3.1. Semantics of kinds and types](#31-semantics-of-kinds-and-types)
  - [3.2. Inclusion and power kinds](#32-inclusion-and-power-kinds)
  - [3.3. Operator kinds](#33-operator-kinds)
  - [3.4. The kind of types](#34-the-kind-of-types)
  - [3.5. Records](#35-records)
- [4. Semantics of Questc](#4-semantics-of-questc)
  - [4.1. Interpretation](#41-interpretation)
  - [4.2. Emulating coercions by bounded quantification](#42-emulating-coercions-by-bounded-quantification)
- [5. Semantics of Quest](#5-semantics-of-quest)
  - [5.1. Preliminaries and structures](#51-preliminaries-and-structures)
  - [5.2. Interpretation](#52-interpretation)
- [Acknowledgements](#acknowledgements)
- [References](#references)

---


<!-- Page 3 -->

## 1. Introduction
Type theory provides a general framework for studying many advanced
programming features including polymorphism, abstract types, modules, and
inheritance. (See [Cardelli Wegner 85] for a survey.) The Quest programming language
[Cardelli 89] attempts to take advantage of this general framework to integrate such
programming constructs into a flexible and consistent whole.
In this paper we focus on the Quest type system, by describing and modeling its
most interesting features. At the core of this system is a three-level structure of kinds,
types (and type operators), and values. Within this structure we accommodate
impredicative type quantifiers and subtyping. Universal type quantifiers can then be
used to model type operators, polymorphic functions, and ordinary higher-order
functions. Existential type quantifiers can model abstract types. Subtyping supports
(multiple) inheritance, and in combination with quantifiers results in bounded-
polymorphic functions and partially abstract types. Subtyping is realized in a uniform
way throughout the system via a notion of power kind, where P (A) is the kind of all
subtypes of A.
Formally, Quest is an extension of Girard's Fω [Girard  \triangleq 2] with additional kind
structure, subtyping structure, recursive types, and fixpoints at all types. Alternatively,
it is a higher-order extension of the calculus studied in [Curien Ghelli 90], which is the
kernel of the calculus in [Cardelli Wegner 85]. Recursion is necessary to model
programming activities adequately, and causes us to abandon the Curry-Howard
isomorphism between formulas and types.
New kinds and types can be easily integrated into the basic Quest system to model
various programming aspects. For example, basic types can be added to model
primitive values and their relations [Mitchell 84]; record and variant types can be
introduced to model object-oriented programming [Cardelli 88, Wand 89, Cardelli Mitchell
89, Cook Hill Canning 90]; and set types can be introduced to model relational data bases
[Ohori 8 \triangleq ]. In all these cases, subtyping performs a major role. Many of these
additional type constructions can however be encoded in a very small core system,
which is the one we investigate in this paper.
The type rules we consider are very powerful, but not particularly complex or
unintuitive from a programming perspective. This contrasts with the semantics of
Quest, which is rather challenging. In particular, difficulties arise when we try to
model simultaneously features such as contravariant function spaces, record types,
subtyping, recursive types, and fixpoints. In this paper we concentrate on modeling
quantifiers and subtyping; recursive types and values are an active subject of research
[Amadio 89] [Abadi Plotkin 90] [Freyd Mulry Rosolini Scott 90].
The model we present for such advanced constructions is particularly simple; the
basic concepts are built on top of elementary set and recursion theory. This model has
been investigated recently within the context of Category Theory, in view of the
relevance of Kleene's realizability interpretation for Category Theory and Logic. Our


<!-- Page 4 -->

presentation applies and further develops, in plain terms and with no general
categorical notions, the work carried on in [Longo Moggi 88] and [Bruce Longo 89]. Our
work is also indebted to that by Amadio, Mitchell, Freyd, Rosolini, Scedrov, Luo and
others (see references).
The presentation of the formal semantics is divided into two parts, corresponding
to sections 4 and 5, where we discuss variants of the language with and without
explicit coercions. However, the underlying mathematical structure is the same and
the interpretations are strictly related.
We conclude this section with a few examples, both to introduce our notation and
to provide some motivation.
The polymorphic identity function below introduces the universal quantifier over
types (Π) along with λ-abstraction over types (λ(X::TYPE)) and type application, and
the function space operator ( \rightarrow ) along with λ-abstraction over values (λ(x:X)) and
value application:
let id : Π(X::TYPE) (X \rightarrow X) =
λ(X::TYPE) λ(x:X) x
id(Int)(3) = 3 : Int
Abstract types are obtained by existential quantification over types (Σ) [Mitchell
Plotkin 85]. (As is well known, these existential quantifiers, with their associated
primitives, can be defined in terms of Π and  \rightarrow . Similarly, cartesian product (×), can
be defined from  \rightarrow .) The following might be the type of a package providing an
abstract type X, a constant of type X, and an operation from X to Int:
Σ(X::TYPE) (X × (X \rightarrow Int))
Bounded universal quantifiers allow us to write functions that are polymorphic
with respect to all the subtypes (<:) of a given type. This is particularly useful for
subtypes of record types, which are generally meant to model object types in object-
oriented programming languages. Here  \langle age:Int \rangle  is the type of records that contain a
field age of type Int, and Üage=5, color=redá is a value of type  \langle age:Int, color:Color \rangle ,
which is a subtype of  \langle age:Int \rangle . The following ageOf function computes the age of
any member of a subtype of  \langle age:Int \rangle .
let ageOf : Π(X<: \langle age:Int \rangle ) (X \rightarrow Int) =
λ(X<: \langle age:Int \rangle ) λ(x:X) x.age
ageOf( \langle age:Int, color:Color \rangle )(Üage=5, color=redá) = 5 : Int


<!-- Page 5 -->

Bounded existential quantifiers are useful for representing types that are partially
abstract in the sense that they are known to be subtypes of a given type, but are not
completely specified:
Σ(X<: \langle age:Int \rangle ) ...
Bounded existential quantifiers also model types that are subtypes of abstract or
partially abstract types:
Σ(X<: \langle age:Int \rangle ) Σ(Y<:X) ...
These last two features are present, in specific forms, in Modula-3 [Cardelli Donahue
Glassman Jordan Kalsow Nelson 88].
We refer to [Cardelli 89] for detailed programming examples that use the full power
of the system.
The paper is organized as follows. Section 2 describes the formal theory of Quest,
including its typing rules, and can be understood on its own. Sections 3, 4, and 5 are
more technical and are concerned with semantics. Section 3 provides background
material on partial equivalence relation (p.e.r.) models, and more specific material on
subtyping. Section 4 gives meaning to Questc (with explicit coercions), while section
5 gives meaning to Quest (with implicit subsumption).
## 2. Quest rules
In this section we discuss the typing and reduction rules for Quest. We use K,L,M
for kinds; A,B,C for types and operators; a,b,c for values; X,Y,Z for type and operator
variables; and x,y,z for value variables. We also use T for the kind of all types, and P
(B) for the kind of subtypes of B. In general, we use capitalized names for kinds and
types, and lower-case names for values.
### 2.1. Terms
The pre-terms are described by the following syntax. Only those pre-terms that
are validated by the rules in the following subsections are legal terms.
K ::= Kinds
P (A) Π(X::K)L the kind of all subtypes of a type
the kind of operators between kinds
A ::= Types and Operators
X type and operator variables


<!-- Page 6 -->

Top the supertype of all types
Π(X::K)B polymorphic types
A \rightarrow B function spaces
λ(X::K)B operators
B(A) operator application
µ(X)A recursive types
a ::= Values
x value variables
top the distinguished value of type Top
λ(X::K)b polymorphic functions
b(A) polymorphic instantiation
λ(x:A)b functions
b(a) function application
cA,B(a) coercions
µ(x:A)a recursive values
The following abbreviations will be used:
T  \triangleq  P (Top) the kind of all types
Π(X)L  \triangleq  Π(X::T )L Π(X<:A)L  \triangleq  Π(X::P (A))L
Π(X)B  \triangleq  Π(X::T )B Π(X<:A)B  \triangleq  Π(X::P (A))B
λ(X)B  \triangleq  λ(X::T )B λ(X<:A)B  \triangleq  λ(X::P (A))B
λ(X)b  \triangleq  λ(X::T )b λ(X<:A)b  \triangleq  λ(X::P (A))b
From the abbreviations above we can see that this calculus includes all the terms of
Fω [Girard  \triangleq 2] and Fun [Cardelli Wegner 85].
### 2.2. Judgments
ones, listed below.
The formal rules are based on eight primitive judgment forms plus three derived
 \vdash  E env E is an environment
E  \vdash  K kind E  \vdash  A::K E  \vdash  A type E  \vdash  a:A E  \vdash  K<::L K is a kind (in an environment E)
type A has kind K
A is a type (abbr. for E  \vdash  A::T )
value a has type A
kind K is a subkind of kind L


<!-- Page 7 -->

E  \vdash  A<:B type A is a subtype of type B (abbr. for E  \vdash  A::P (B))
E  \vdash  K<::>L E  \vdash  A<:>B::K E  \vdash  A<:>B type E  \vdash  a \cong b:A K and L are equivalent kinds
A and B are equivalent types or operators of kind K
A and B are equivalent types (abbr. for E  \vdash  A<:>B::T )
a and b are equivalent values
A judgment like E  \vdash  a:A is interpreted as defining a relation between
environments, value terms, and type terms. This relation is defined inductively by
axioms and inference rules, as described in the following sections. The rules are then
summarized in section 2.9.
### 2.3. Environments and variables
An environment E is a finite sequence of type variables associated with kinds, and
value variables associated with types. We use dom(E) for the set of type and value
variables defined in an environment.
[Env  \emptyset ] [Env X] [Env x]
E  \vdash  K kind X \notin dom(E) E  \vdash  A type x \notin dom(E)
 \vdash   \emptyset  env  \vdash  E,X::K env  \vdash  E,x:A env
[Var X] [Var x]
 \vdash  E',X::K,E" env E',X::K,E"  \vdash  X :: K  \vdash  E',x:A,E" env
E',x:A,E"  \vdash  x : A
### 2.4. Equivalence and inclusion
Equivalence of kinds (<::>) is the least congruence relation over the syntax of
kinds that includes the following rule involving type equivalence:
[KEq P]
E  \vdash  A<:>A' type
E  \vdash  P (A) <::> P (A')
Equivalence of types and operators (<:>) is the least congruence relation over the
syntax of types that includes β and η type conversions (shown later), and the
following rule for recursive types. Here A \succ X means that A must be contractive in X
in order to avoid non-well-founded recursions; see the definition in 2.9. The third rule
below claims that every contractive context C has a unique fixpoint.
[TF µ]
E, X::T  \vdash  A type A \succ X


<!-- Page 8 -->

E  \vdash  µ(X)A type
[T µ]
E,X::T  \vdash  A type A \succ X
E  \vdash  µ(X)A <:> A{X \leftarrow µ(X)A} type
[TEq Contract]
E  \vdash  A<:>C{X \leftarrow A} type E  \vdash  B<:>C{X \leftarrow B} type C \succ X
E  \vdash  A <:> B type
Inclusion of recursive types is given by the following rule, working inductively from
the inclusion of the recursive variables to the inclusion of the recursive bodies:
[TIncl µ]
E  \vdash  µ(X)A type E  \vdash  µ(Y)B type E  \vdash  µ(X)A <: µ(Y)B
E, Y::T, X<:Y  \vdash  A <: B
Equivalence of values ( \cong ) is the least congruence relation over the syntax of
values that includes β and η value conversions (shown later), together with the
following rule for recursive values:
[µ]
E  \vdash  µ(x:A)b : A
E  \vdash  µ(x:A)b  \cong  b{x \leftarrow µ(x:A)b} : A
The rules for recursive types and values will not be modeled in the later sections.
Nonetheless, we consider them an essential part of the language, and refer the reader
to [Amadio 89], [Abadi Plotkin 90], and [Freyd Mulry Rosolini Scott 90] for related and
ongoing work.
The following rules state that the property of having a kind (respectively a type) is
invariant under kind (respectively type) equivalence; that is, equivalent kinds and
types have the same extensions:
[KExt] (Kind Extension) [TExt] (Type Extension)
E  \vdash  A::K E  \vdash  K<::>L E  \vdash  a:A E  \vdash  A<:>B type
E  \vdash  A :: L E  \vdash  a : B
The relations of type and kind inclusion are reflexive and transitive:
[KIncl Refl] [KIncl Trans]
E  \vdash  K <::> L E  \vdash  K <:: L E  \vdash  L <:: M


<!-- Page 9 -->

E  \vdash  K <:: L [TIncl Refl] [TIncl Trans]
E  \vdash  A <:> B type E  \vdash  A <: B E  \vdash  K <:: M
E  \vdash  A <: B E  \vdash  B <: C
E  \vdash  A <: C
We shall see shortly that the subtype relation is actually defined in terms of power
kinds, then all the rules written in terms of subtyping are interpreted as rules about
power kinds.
### 2.5. Subsumption vs. coercion
The following rules reflect the set-theoretical intuitions behind the subtyping
relation. We present two alternatives: subsumption and coercion.
Subsumption formalizes a computationally natural way of looking at subtypes.
When viewing computations as type-free activities, any element of a type is directly
an element of its supertypes:
[TSub] (Subsumption)
E  \vdash  a:A E  \vdash  A<:B
E  \vdash  a : B
A mathematical model of Quest with subsumption is given in part 5. That model
is the main semantic novelty of this paper.
Before that, in part 4, we consider a system without subsumption, called Questc.
In Questc, subsumption is replaced by a coercion rule, where a value of a type A must
be explicitly injected into a supertype B by a coercion function cA,B. Invariance under
type inclusion will be true only modulo coercions in the most straightforward
semantics given in part 4.
[TSub] (Coercion)
E  \vdash  a:A E  \vdash  A<:B
E  \vdash  cA,B(a) : B
In the semantics of Questc we obtain a single coercion function c: Π(X::T ) Π(Y<:X)
Y \rightarrow X; then c(B)(A) gives meaning to cA,B.
Coercions satisfy the following basic rules; more rules will be given later.
[VCoer Id / Questc] E  \vdash  a:A [VCoer Comp / Questc]
E  \vdash  a:A E  \vdash  A<:B E  \vdash  B<:C
E  \vdash  cA,A(a)  \cong  a : A E  \vdash  cB,C(cA,B(a))  \cong  cA,C(a) : C


<!-- Page 10 -->

The important intuition about coercions is that they involve little, if any,
computational work. Often they are introduced as identity functions with the only
purpose of "getting the types right". In compilation practice they are often removed
during code generation. Semantically, this will be understood in the model for Questc
below by observing that they are computed by (indexes of) the identity function. In
Quest, the subsumption rule above is a strong (or explicit) way of saying that
coercions have no computational relevance.
### 2.6. Power kinds
For each type A there is a kind P (A) of all subtypes of A. The kind P (Top) is then
the kind of all types, and is called T. Here are the formation and introduction rules for
P ; the subsumption/coercion rule serves as an elimination rule for P .
[KF P] [TIncl Refl']
E  \vdash  A type E  \vdash  P (A) kind E  \vdash  A type
E  \vdash  A :: P (A)
The subtype judgment E  \vdash  A<:B is defined as an abbreviation for a judgment
involving power kinds:
E  \vdash  A <: B iff E  \vdash  A :: P (B)
The subkind judgment E  \vdash  K<::L is primitive, but has very weak properties. It is
reflexive and transitive, it extends monotonically to P , and it extends to Π via a
covariant rule:
[KIncl P] [KIncl Π]
E  \vdash  A<:A' E  \vdash  P (A) <:: P (A') E  \vdash  K kind E, X::K  \vdash  L <:: L'
E  \vdash  Π(X::K)L <:: Π(X::K)L'
Note that the first rule above implies P (A) <:: T.
Moreover, we have a subsumption rule on kinds:
[KSub] (Kind Subsumption)
E  \vdash  A::K E  \vdash  K<::L
E  \vdash  A :: L
Unlike type subsumption, kind subsumption is satisfied by both models in parts 4 and
5.


<!-- Page 11 -->

2. \triangleq  Operator kinds
The kind of type operators is normally written as K \implies  L in Fω (operators from
kind K to kind L). In our system, as in the Theory of Constructions, we use a more
general construction Π(X::K)L since X may actually occur in L within a power
operator, for example in Π(X::T ) P (X).
Individual operators are written λ(X::K)A with standard introduction, elimination,
and computation rules, shown later.
### 2.8. The kind of types
The kind of all types T contains the type Top, the types of polymorphic functions,
the types of ordinary functions, and the recursive types.
The type Top is the maximal element in the subtype order:
[TF Top] [TIncl Top]
 \vdash  E env E  \vdash  Top type E  \vdash  A type
E  \vdash  A <: Top
Hence the power of Top is the collection of all types and, as already mentioned, we
can define the kind of all types as follows:
T = P (Top)
There is a canonical element of type Top, called top. Moreover, any value
belonging to Top is indistinguishable from top:
[VI Top] [VEqTop'] (Top Collapse)
 \vdash  E env E  \vdash  a:Top E  \vdash  b:Top
E  \vdash  top : Top E  \vdash  a  \cong  b : Top
When using the subsumption rule, we obtain that every value has type Top, since
Top is the largest type. Moreover, every value is equivalent to top when seen as a
member of Top, and hence cA,Top(a)  \cong  cB,Top(b) for any a:A and b:B. By this, when
using the coercion rule, there is a unique coercion cA,Top(a) from A into Top. This
rather peculiar situation will be understood in the semantics by the meaning of <: and
by the interpretation of Top as the terminal object in the intended category. Top and
its properties will play a crucial role in the coding of records.
The types of polymorphic functions are modeled by an impredicative general-
product construction, Π(X::K)B. Although we do not show it here, from this product


<!-- Page 12 -->

we can derive "weak" general sums, which are used in the Quest language for
modeling abstract types.
The standard formation, introduction, elimination, and computation rules (shown
in section 2.9) are complemented by rules for subtyping and coercion:
[TIncl Π]
E  \vdash  K'<::K E, X::K'  \vdash  B<:B'
E  \vdash  Π(X::K)B <: Π(X::K')B'
[VCoer Π]
E  \vdash  b : Π(X::K)B E  \vdash  A : K' E  \vdash  Π(X::K)B <: Π(X::K')B'
E  \vdash  (cΠ(X::K)B,Π(X::K')B'(b))(A)  \cong  cB{X \leftarrow A},B'{X \leftarrow A}(b(A)) : B'{X \leftarrow A}
Ordinary higher-type functions are modeled by a function space construction ( \rightarrow ).
We avoid first-order dependent types (Π(x:A)B, which generalize A \rightarrow B) because in
practice they are hard to typecheck and compile. Again, most rules are standard, but
we may want to notice subtyping and coercion:
[TIncl  \rightarrow ]
E  \vdash  A'<:A E  \vdash  B<:B'
E  \vdash  A \rightarrow B <: A' \rightarrow B'
[VCoer  \rightarrow ]
E  \vdash  b : A \rightarrow B E  \vdash  a : A' E  \vdash  A \rightarrow B <: A' \rightarrow B'
E  \vdash  (cA \rightarrow B,A' \rightarrow B'(b))(a)  \cong  cB,B'(b(cA',A(a)) : B'
### 2.9. Formal system
In this section we summarize the formal systems for both Quest and Questc. The
rules of these systems are presented simultaneously as they largely coincide.
Rules are named, for example, [TExt / Quest] (Type Extension) extra. Here TExt is the proper
name of the rule. The notation / Quest means that this rule applies only to Quest, while
the notation / Questc applies only to Questc; otherwise the rule applies to both systems.
This rule is sometimes called Type Extension in the text. Finally, extra means that this rule is
actually derivable or admissible and is listed for symmetry with other rules or for
emphasis (for example, [KEq Refl] and [TEq Refl] are provable by simultaneous induction
on the derivations).
The rules grouped as "computation" rules may be oriented in order to provide
reduction strategies.


<!-- Page 13 -->

A recursive type µ(X)C is legal only if C is contractive in X, written C \succ X
[MacQueen Plotkin Sethi 86]. A type C is contractive in a (free) type variable X if and
only if C has one of the following six forms: a type variable different from X; Top;
Π(X'::K)C' with X \notin free-variables(K) and C' \succ X; A \rightarrow B; (λ(X'::K)B)(A) with
B{X' \leftarrow A} \succ X; or µ(X')C' with C' \succ X (as well as C' \succ X').
We are conservative about the contractiveness conditions on Π(X'::K)C, and these
deserve further study. The condition X \notin free-variables(K) prevents constructions such
as µ(X)Π(Y<:X)X \rightarrow X, whose semantics is unclear. The condition C' \succ X agrees with
one of the semantics we give to Π as a non-expansive intersection, although
syntactically this restriction seems unnecessary.
Judgments
 \vdash  E env E is an environment
E  \vdash  K kind E  \vdash  A::K E  \vdash  A type E  \vdash  a:A K is a kind (in an environment E)
type A has kind K
A is a type (abbr. for E  \vdash  A::T )
value a has type A
E  \vdash  K<::L E  \vdash  A<:B kind K is a subkind of kind L
type A is a subtype of type B (abbr. for E  \vdash  A::P (B))
E  \vdash  K<::>L E  \vdash  A<:>B::K E  \vdash  A<:>B type E  \vdash  a \cong b:A K and L are equivalent kinds
A and B are equivalent types or operators of kind K
A and B are equivalent types (abbr. for E  \vdash  A<:>B::T )
a and b are equivalent values
Environments
[Env  \emptyset ] [Env X] [Env x]
E  \vdash  K kind X \notin dom(E) E  \vdash  A type x \notin dom(E)
 \vdash   \emptyset  env  \vdash  E,X::K env  \vdash  E,x:A env
[Var X] [Var x]
 \vdash  E',X::K,E" env E',X::K,E"  \vdash  X :: K  \vdash  E',x:A,E" env
E',x:A,E"  \vdash  x : A
Kind formation
[KF P] [KF Π]
E  \vdash  A type E  \vdash  P (A) kind E  \vdash  K kind E, X::K  \vdash  L kind
E  \vdash  Π(X::K)L kind


<!-- Page 14 -->

Kind equivalence
[KEq Refl] extra [KEq Symm] [KEq Trans]
E  \vdash  K kind E  \vdash  K <::> L E  \vdash  K <::> L E  \vdash  L <::> M
E  \vdash  K <::> K E  \vdash  L <::> K E  \vdash  K <::> M
[KEq P] [KEq Π]
E  \vdash  A<:>A' type E  \vdash  K <::> K' E, X::K  \vdash  L <::> L'
E  \vdash  P (A) <::> P (A') E  \vdash  Π(X::K)L <::> Π(X::K')L'
[KExt] (Kind Extension) extra
E  \vdash  A::K E  \vdash  K<::>L
E  \vdash  A :: L
Kind inclusion
[KIncl Refl] [KIncl Trans]
E  \vdash  K <::> L E  \vdash  K <:: L E  \vdash  L <:: M
E  \vdash  K <:: L E  \vdash  K <:: M
[KIncl P] [KIncl Π]
E  \vdash  A<:A' E  \vdash  K kind E, X::K  \vdash  L <:: L'
E  \vdash  P (A) <:: P (A') E  \vdash  Π(X::K)L <:: Π(X::K)L'
[KSub] (Kind Subsumption)
E  \vdash  A::K E  \vdash  K<::L
E  \vdash  A :: L
Type and Operator formation
[TF Top] [TF µ]
 \vdash  E env E  \vdash  Top type E, X::T  \vdash  A type A \succ X
E  \vdash  µ(X)A type
[TF Π] [TF  \rightarrow ]
E  \vdash  K kind E, X::K  \vdash  B type E  \vdash  Π(X::K)B type E  \vdash  A type E  \vdash  B type
E  \vdash  A \rightarrow B type
[TI Π] [TE Π]
E  \vdash  K kind E, X::K  \vdash  B::L E  \vdash  λ(X::K)B :: Π(X::K)L E  \vdash  B::Π(X::K)L E  \vdash  A::K
E  \vdash  B(A) :: L{X \leftarrow A}
Type and Operator equivalence
[TEq Refl] extra [TEq Symm] [TEq Trans]
E  \vdash  A :: K E  \vdash  A <:> B :: K E  \vdash  A <:> A :: K E  \vdash  B <:> A :: K E  \vdash  A <:> B :: K E
\vdash  B <:> C :: K
E  \vdash  A <:> C :: K


<!-- Page 15 -->

[TEq X] [TEq Top]
E  \vdash  X :: K  \vdash  E env
E  \vdash  X <:> X :: K E  \vdash  Top <:> Top type
[TEq Π] [TEq  \rightarrow ]
E  \vdash  K<::>K' E, X::K  \vdash  B<:>B' type E  \vdash  Π(X::K)B <:> Π(X::K')B' type E  \vdash  A<:>A' type E  \vdash
B<:>B' type
E  \vdash  A \rightarrow B <:> A' \rightarrow B' type
[TEq Abs] [TEq Appl]
E  \vdash  K<::>K' E, X::K  \vdash  B<:>B' :: L E  \vdash  λ(X::K)B <:> λ(X::K')B' :: Π(X::K)L E  \vdash  B<:>B' ::
Π(X::K)L E  \vdash  A<:>A' :: K
E  \vdash  B(A) <:> B'(A') :: L{X \leftarrow A}
[TEq µ] [TEq Contract]
E, X::T  \vdash  B<:>B' type B,B' \succ X E  \vdash  A<:>C{X \leftarrow A} type E  \vdash  B<:>C{X \leftarrow B} type C
\succ X
E  \vdash  µ(X)B <:> µ(X)B' type E  \vdash  A <:> B type
[TExt / Quest] (Type Extension) extra E  \vdash  a:A E  \vdash  A<:>B type E  \vdash  a : B [TExt / Questc] (Type
Extension)
E  \vdash  a:A E  \vdash  A<:>B type
E  \vdash  a : B
[T Π η]
E  \vdash  B :: Π(X::K)L X \notin dom(E)
E  \vdash  (λ(X::K)B(X)) <:> B :: Π(X::K)L
Type and Operator computation
[T Π β]
E  \vdash  (λ(X::K)B)(A) :: L
E  \vdash  (λ(X::K)B)(A) <:> B{X \leftarrow A} :: L
[T µ]
E,X::T  \vdash  A type A \succ X
E  \vdash  µ(X)A <:> A{X \leftarrow µ(X)A} type
Type inclusion
[TIncl Refl] [TIncl Trans]
E  \vdash  A <:> B type E  \vdash  A <: B E  \vdash  A <: B E  \vdash  B <: C
E  \vdash  A <: C
[TIncl Top] [TIncl Π] [TIncl  \rightarrow ]
E  \vdash  A type E  \vdash  K'<::K E, X::K'  \vdash  B<:B' E  \vdash  A'<:A E  \vdash  B<:B'
E  \vdash  A <: Top E  \vdash  Π(X::K)B <: Π(X::K')B' E  \vdash  A \rightarrow B <: A' \rightarrow B'
[TIncl µ]
E  \vdash  µ(X)A type [TSub / Quest] (Subsumption) E  \vdash  µ(Y)B type E  \vdash  µ(X)A <: µ(Y)B
[TSub / Questc] (Coercion)
E, Y::T, X<:Y  \vdash  A <: B


<!-- Page 16 -->

E  \vdash  a:A E  \vdash  A<:B E  \vdash  a:A E  \vdash  A<:B
E  \vdash  a : B E  \vdash  cA,B(a) : B
Value formation
[VI Top]
 \vdash  E env
E  \vdash  top : Top
[VI Π] [VE Π]
E  \vdash  K kind E, X::K  \vdash  b:B E  \vdash  λ(X::K)b : Π(X::K)B E  \vdash  b:Π(X::K)B E  \vdash  A::K
E  \vdash  b(A) : B{X \leftarrow A}
[VI  \rightarrow ] [VE  \rightarrow ]
E  \vdash  A type E, x:A  \vdash  b:B E  \vdash  λ(x:A)b : A \rightarrow B E  \vdash  b:A \rightarrow B E  \vdash  b(a)
: B
E  \vdash  a:A
[VI c / Questc]
E  \vdash  A <: B E  \vdash  a:A
E  \vdash  cA,B(a) : B
[VI µ]
E  \vdash  A type E, x:A  \vdash  b:A
E  \vdash  µ(x:A)b : A
Value equivalence
[VEq Refl] extra [VEq Symm] [VEq Trans]
E  \vdash  a : A E  \vdash  a  \cong  b : A E  \vdash  a  \cong  b : A E  \vdash  b  \cong  c : A
E  \vdash  a  \cong  a : A E  \vdash  b  \cong  a : A E  \vdash  a  \cong  c : A
[VEqSub / Quest] (Subsumption Eq) E  \vdash  a \cong a':A E  \vdash  A<:BE  \vdash  a \cong a':A [VEqSub / Questc]
(Coercion Eq)
E  \vdash  A<:B E  \vdash  A<:>A' type E  \vdash  B<:>B'
type
E  \vdash  a \cong a' : B E  \vdash  cA,B(a) \cong cA',B'(a') : B
[VEq x] [VEq top] [VEqTop] (Top Collapse)
E  \vdash  x:A  \vdash  E env E  \vdash  a  \cong  a : Top E  \vdash  b  \cong  b : Top
E  \vdash  x  \cong  x : A E  \vdash  top  \cong  top : Top E  \vdash  a  \cong  b : Top
[VEq TAbs] [VEq TAppl]
E  \vdash  K<::>K' E, X::K  \vdash  b  \cong  b' : B E  \vdash  λ(X::K)b  \cong  λ(X::K')b' : Π(X::K)B E  \vdash  b
\cong b' :: Π(X::K)B E  \vdash  A<:>A' :: K
E  \vdash  b(A)  \cong  b'(A') : B{X \leftarrow A}
[VEq Abs] [VEq Appl]
E  \vdash  A<:>A' type E, x:A  \vdash  b  \cong  b' : B E  \vdash  λ(x:A)b  \cong  λ(x:A')b' : A \rightarrow B E  \vdash
b \cong b' : A \rightarrow B E  \vdash  a \cong a' : A
E  \vdash  b(a)  \cong  b'(a') : B


<!-- Page 17 -->

[VEq µ]
E  \vdash  A<:>A' type E, x:A  \vdash  b  \cong  b' : A
E  \vdash  µ(x:A)b  \cong  µ(x:A')b' : A
[Π η / Questc] E  \vdash  b : Π(X::K)B X \notin dom(E) E  \vdash  (λ(X::K)b(X))  \cong  b : Π(X::K)B [ \rightarrow  η /
Questc]
E  \vdash  b : A \rightarrow B x \notin dom(E)
E  \vdash  (λ(x:A)b(x))  \cong  b : A \rightarrow B
Value coercion
[VCoer Id / Questc] E  \vdash  a:A [VCoer Comp / Questc]
E  \vdash  a:A E  \vdash  A<:B E  \vdash  B<:C
E  \vdash  cA,A(a)  \cong  a : A [VCoer Top / Questc] extra
E  \vdash  a : A
E  \vdash  cB,C(cA,B(a))  \cong  cA,C(a) : C
E  \vdash  cA,Top(a)  \cong  top : Top
[VCoer Π / Questc]
E  \vdash  b : Π(X::K)B E  \vdash  A : K' E  \vdash  Π(X::K)B <: Π(X::K')B'
E  \vdash  (cΠ(X::K)B,Π(X::K')B'(b))(A)  \cong  cB{X \leftarrow A},B'{X \leftarrow A}(b(A)) : B'{X \leftarrow A}
[VCoer  \rightarrow  / Questc]
E  \vdash  b : A \rightarrow B E  \vdash  a : A' E  \vdash  A \rightarrow B <: A' \rightarrow B'
E  \vdash  (cA \rightarrow B,A' \rightarrow B'(b))(a)  \cong  cB,B'(b(cA',A(a)) : B'
[VCoer µ / Questc]
E  \vdash  a : µ(X)A E  \vdash  A : K' E  \vdash  µ(X)A <: µ(Y)B
E  \vdash  cµ(X)A,µ(Y)B(a)  \cong  cA{X \leftarrow µ(X)A},B{Y \leftarrow µ(Y)}(a) : µ(Y)B
Value computation
[Π β] [ \rightarrow  β]
E  \vdash  (λ(X::K)b)(A) : B E  \vdash  (λ(X::K)b)(A)  \cong  b{X \leftarrow A} : B E  \vdash  (λ(x:A)b)(a) : B
E  \vdash  (λ(x:A)b)(a)  \cong  b{x \leftarrow a} : B
[µ]
E  \vdash  µ(x:A)b : A
E  \vdash  µ(x:A)b  \cong  b{x \leftarrow µ(x:A)b} : A
### 2.10. Records and other encodings
Record types are one of the main motivations for studying type systems with
subtyping [Cardelli 88]. However, in this paper we do not need to model them directly
(as already done in [Bruce Longo 89]), since they can be syntactically encoded to a great
extent.


<!-- Page 18 -->

More precisely, we show how to encode the record calculus of [Cardelli Wegner 85],
although we do not know yet how to encode the more powerful calculi of [Wand 89]
and [Cardelli Mitchell 89]. Moreover, we show how to encode the functional update
problem discussed in [Cardelli Mitchell 89]; this problem cannot be represented in the
calculus of [Cardelli Wegner 85].
In this section we discuss these encodings, and then we feel free to ignore records
in the rest of the paper.
We start by encoding product types, in the usual way:
A×B  \triangleq  Π(C)(A \rightarrow B \rightarrow C) \rightarrow C
pair : Π(A) Π(B) A \rightarrow B \rightarrow A×B
 \triangleq  λ(A) λ(B) λ(a:A) λ(b:B) λ(C) λ(f:A \rightarrow B \rightarrow C) f(a)(b)
fst : Π(A) Π(B) A×B \rightarrow A
 \triangleq  λ(A) λ(B) λ(c:A×B) c(A)(λ(x:A)λ(y:B)x)
snd : Π(A) Π(B) A×B \rightarrow B
 \triangleq  λ(A) λ(B) λ(c:A×B) c(B)(λ(x:A)λ(y:B)y)
We often use a more compact notation:
a,b  \triangleq  a,A×Bb  \triangleq  pair(A)(B)(a)(b)
fst(c)  \triangleq  fstA×B(c)  \triangleq  fst(A)(B)(c)
snd(c)  \triangleq  sndA×B(c)  \triangleq  snd(A)(B)(c)
The expected rules for products are now derivable:
E  \vdash  A <: A' E  \vdash  B <: B'
E  \vdash  A×B <: A'×B'
E  \vdash  P <: A×B E  \vdash  p:P E  \vdash  fstA×B(p) : A E  \vdash  P <: A×B E  \vdash  p:P
E  \vdash  sndA×B(p) : B
As a first step toward records, we define extensible tuple types as iterated products
ending with Top, and extensible tuple values as iterated pairs ending with top. A
similar encoding appears in [Fairbairn 89].
Tuple(A1,...,An)  \triangleq  A1×(...×(An×Top)..)
tuple(a1,...,an)  \triangleq  a1,(...,(an, top)..)


<!-- Page 19 -->

Hence:
E  \vdash  a1 : A1 ... E  \vdash  an : An
E  \vdash  tuple(a1,...,an) : Tuple(A1,...,An)
E  \vdash  A1 <: B1 ... E  \vdash  An <: Bn ... E  \vdash  Am type
E  \vdash  Tuple(A1,...,An,...,Am) <: Tuple(B1,...,Bn)
For example: Tuple(A, B) <: Tuple(A) since A <: A, B×Top <: Top, and × is
monotonic.
We now need to define tuple selectors (corresponding to product projections).
This would be a family selin of terms selecting the i-th components of a tuple of
length n. In fact, by using subtyping it is sufficient to define a family seli of terms for
extracting the i-th component of any tuple of sufficient length:
sel1 : Π(A1) A1×Top \rightarrow A1
 \triangleq  λ(A1) λ(t:A1×Top) fstA1×Top(t)
sel2 : Π(A2) Top×A2×Top \rightarrow A2
 \triangleq  λ(A2) λ(t:Top×A2×Top)
fstA2×Top(sndTop×A2×Top(t))
etc.
We can also define tuple updators, that is, terms that replace the i-th component of
a tuple with a given value. The crucial point here is that these updators do not forget
information about the type of the components that are not affected by the update. To
achieve this effect, we must use knowledge of the encoding of tuples as pairs. Again,
we can define a family updi instead of a family updin
.
upd1 : Π(B1) Π(Btl) Π(A1) B1×Btl \rightarrow A1 \rightarrow A1×Btl
 \triangleq  λ(B1) λ(Btl) λ(A1)
λ(t:B1×Btl) λ(a1:A1) a1,A1×Btl
sndB1×Btl(t)
upd2 : Π(B1) Π(B2) Π(Btl) Π(A2) B1×B2×Btl \rightarrow A2 \rightarrow B1×A2×Btl
 \triangleq  λ(B1) λ(B2) λ(Btl) λ(A2)
λ(t:B1×B2×Btl) λ(a2:A2) fst(t),(a2, snd(snd(t)))
etc.


<!-- Page 20 -->

These definitions solve the functional update problem [Cardelli Mitchell 89] for
tuples. This problem can be explained by the following example, where we update a
field of a tuple in such a way that the updating function works equally well on
subtypes of the stated tuple type.
We have a type of geometric points defined as Point = Tuple(Int,Int), where the
integers represent respectively the x and y components. Since these are tuples, a point
can have additional components, for example a color; then it is a member of
ColorPoint = Tuple(Int,Int,Color). We further assume that the subrange type 0..9 is a
subtype of Int.
The problem consists in defining a function moveX that increments the x
component of a point, returning another Point. Moreover, when applied to a
ColorPoint (with adequate type parameters) this function should return a ColorPoint,
and not just a Point.
One might think that moveX has type Π(A<:Point) A \rightarrow A. This is not the case; we
show that the parameter type A must change appropriately from input to output.
Point  \triangleq  Tuple(Int,Int)
moveX : Π(B1<:Int) Π(Btl<:Tuple(Int)) B1×Btl \rightarrow Int×Btl
 \triangleq  λ(B1<:Int) λ(Btl<:Tuple(Int)) λ(p:B1×Btl)
upd1(B1)(Btl)(Int)(p)(sel1(Int)(p)+1)
Obviously, we have:
p : Point  \triangleq  tuple(9,0)
moveX(Int)(Tuple(Int))(p)  \triangleq  tuple(10,0) : Point
However, note that in the following example the result does not, and must not, have
type Tuple(0..9,Int):
p : Tuple(0..9,Int) <: Point  \triangleq  tuple(9,0)
moveX(0..9)(Tuple(Int))(p)  \triangleq  tuple(10,0) : Point
We can also verify that color is preserved:
p : Tuple(0..9,Int,Color) <: ColorPoint  \triangleq  tuple(9,0,red)
moveX(0..9)(Tuple(Int,Color))(p)  \triangleq  tuple(10,0,red) : ColorPoint
Hence, we obtain a moveX function with the desired properties, but only by
taking advantage of the encoding of tuples as products. Note that in the input type of
moveX, Point is split into Int and Tuple(Int).


<!-- Page 21 -->

Now we turn to the encoding of records Rcd(l1:A1, ... ,ln:An); these are unordered
product types with components indexed by distinct labels li.
We fix a standard enumeration of labels l 1, l 2, ... . Then a record type is the
shortest tuple type where the type component of label l i is found in the tuple slot of
index i, for each i. The remaining slots are filled with Top. For example:
Rcd(l 3:C, l 1:A)  \triangleq  Tuple(A, Top, C)
Under this encoding, record types that differ only on the order of components are
equivalent, and we have the familiar:
E  \vdash  A1 <: B1 ... E  \vdash  An <: Bn ... E  \vdash  Am type
E  \vdash  Rcd(l1:A1,...,ln:An,...,lm:Am) <: Rcd(l1:B1,...,ln:Bn)
Record values are similarly encoded, for example:
rcd(l 3=c, l 1=a)  \triangleq  tuple(a, top, c)
E  \vdash  a1 : A1 ... E  \vdash  an : An
E  \vdash  rcd(l1=a1,...,ln=an) : Rcd(l1:A1,...,ln:An)
E  \vdash  r : Rcd(l1:A1,...,l1:An) E  \vdash  r.li : Ai E  \vdash  r : Rcd(l1:A1,...,li:Ai,...,l1:An) E  \vdash  b:B
E  \vdash  r.li \leftarrow b : Rcd(l1:A1,...,li:B,...,ln:An)
Here record selection r.li is defined via seli(r), and record update r.li \leftarrow b is defined via
updi(r)(b).
Note that it is not possible to write a version of moveX for records solely by using
the derived operators above. The functional update problem can be solved only by
using knowledge of the encodings, as was done for tuples. In this respect (an encoding
of) a calculus like the one in [Cardelli Mitchell 89] is still to be preferred, since it can
express the moveX functions independently of encodings.
Under the encodings above, more programs are typable than we would normally
desire; this is to be expected of any encoding strategy. The important point here is that
the familiar typing and computation rules are sound.
3. PER and ω-Set
The rest of the paper describes the mathematical meaning of the Quest system
described in the previous section. The goal here is to guarantee the (relative)
consistency of Quest's type and equational theories. The model though is also meant


<!-- Page 22 -->

to suggest consistent extensions. This is one of the reasons for which we construct a
specific (class of) model(s), instead of suggesting general definitions. These may be
obtained by slight modifications of the work in [Bruce Longo 88] , or, even better, by
following the categorical approach in [Asperti Longo 91]. Indeed, in the latter case, the
invention of a general categorical meaning for subtyping and subkinds would be a
relevant contribution.
In this part, we first try to give the structural (and partly informal) meaning of
kinds, types, and terms, as well as their crucial properties. The reader will find the
properties formally described in part 2 reflected over sets and functions, and should
grasp the essence of the translation. Part 4 develops further the details of the
interpretation of Questc that the experienced reader could give by himself, at that
point. Part 5 describes Quest with the subsumption rule, instead of with coercions.
Because of the presence of type operators, the structure of kinds is at least as rich
as the type-structure of typed λ-calculus. Thus, kinds need to be interpreted as objects
of a Cartesian Closed Category, CCC. The category we will be using is ω-Set below.
Its objects must, of course, include the kind of types, which in turn must be structured
as a CCC.
In a sense, we need a frame (or global) category, inside which we may view the
category of types as an object. More precisely, we need a frame category and an
internal category, but we will not go into this here, except in remark 3.1.5. The
general approach by internal categories was suggested by Moggi and has been
developed by several authors; see 3.1.5 for references.
The specific structures used here, that is ω-Set and PER below, are described in
[Longo Moggi 88], where their main categorical properties are also given. The approach
in [Longo Moggi 88] is elementary: indeed, these categories may be seen as
subcategories of Hyland's Effective Topos (see [Hyland 82 and 8 \triangleq ] for the topos theoretic
approach). The idea of interpreting subtypes as subrelations is borrowed from [Bruce
Longo 89], where the semantics of Quest's progenitor system, Bounded Fun (with
coercions), was first given.
### 3.1. Semantics of kinds and types
The key idea in the underlying mathematical construction is to use a set-theoretic
approach where the addition of some effectiveness prevents the difficulties discussed
in [Reynolds 84]. In this regard, the blend of set-theoretic intuition and elementary
computability provides a simple but robust guideline for the interpretation of
programming constructs.
The construction is based on Kleene's applicative structure (ω,
 \cdot ), where ω is the
set of natural numbers, together with a standard gödelization ϕn of the computable
functions in ω \rightarrow ω, and where  \cdot  is the operator such that n \cdot m = ϕn(m). However, the
same mathematical construction works for any (possibly partial) combinatory algebra,


<!-- Page 23 -->

in particular on any model of type-free λ-calculus. We prefer, in this part, Kleene's (ω,
 \cdot ) in view of everybody's familiarity with elementary recursion theory. In part 5,
though, we will base our construction on models of the type-free λ-calculus.
Definition 3.1.1
The category ω-Set has:
objects: 〈A,  \Vdash A〉 ∈ ω-Set iff
A is a set and  \Vdash A ⊆ ω×Α is a relation, such that ∀a∈A. ∃n. n  \Vdash A a
morphisms: f ∈ ω-Set[A,B] iff
f: A  \rightarrow  B and ∃n. n  \Vdash A \rightarrow B f,
where n  \Vdash A \rightarrow B f  \iff  ∀a∈A. ∀p. p  \Vdash A a  \implies  n \cdot p  \Vdash B f(a) M
Thus, each morphism in ω-Set is "computable" in the sense that it is described by
a partial recursive function that is total on {p | p  \Vdash A a}, for each a∈A. If p  \Vdash  a (we
may omit the subscripts), we say that p realizes a (or p computes a).
We next define the category of types. When A is a symmetric and transitive
relation on ω, we set:
n A m iff n is related to m by A,
dom(A) = {n | n A n},
“ “
” ”
n
A = {m | m A n} the equivalence class of n with respect to A,
Q(A) = {“
”
n
A | n ∈ dom(A)} the quotient set of A.
Definition 3.1.2
The category PER (of Partial Equivalence Relations) has
objects: A∈PER iff
A is a symmetric and transitive relation on ω,
morphisms: f∈PER[A,B] iff
f: Q(A)  \rightarrow  Q(B) and ∃n. ∀p. (pAp  \implies  f(“
p”
A) = “
n \cdot p”
B) M
PER is a category where the identity map, in each type, is computed by (at least)
any index of the identity function on ω.
The category PER can be fully and faithfully embedded into ω-Set. In fact, for
every partial equivalence relation (p.e.r.) A, define the ω-set In(A) = 〈Q(A), ∈A〉,
where Q(A) are the equivalence classes of A as subsets of ω, and ∈A is the usual
membership relation restricted to ω×Q(A). Clearly, ∈A defines a realizability relation
in the sense of 3.1.1 and the functor In is full and faithful. Note that ∈A is a single-
valued relation, as equivalence classes are disjoint subsets of ω.
The following simple fact may help in identifying which are the maps in PER, by
viewing them also as morphisms in ω-Set. (The reader should practice going from one
category to the other; the next proposition is just an exercise with this purpose.)


<!-- Page 24 -->

Proposition 3.1.3
Let f ∈ PER[A,C], then
p  \Vdash A \rightarrow C f (in ω-Set)  \iff  ∀r. (r A r  \implies 
“
”
p \cdot r
C = f(“
”
r
A))
Proof
p  \Vdash A \rightarrow C f  \iff  ∀a∈Q(A). ∀r  \Vdash A a. p \cdot r  \Vdash C f(a)
 \iff  ∀r. r A r  \implies  p \cdot r ∈ f(“
”
r
A),
since  \Vdash  coincides with ∈ (with respect to an equivalence class).
Hence we must show:
∀r. (r A r  \implies  p \cdot r ∈ f(“
”
r
A))  \iff  ∀r. (r A r  \implies 
“
”
p \cdot r
C = f(“
”
r
A)).
Case ùõü) Obvious, since p \cdot r ∈ “
”
p \cdot r
C
Case  \implies ) Suppose “
”
p \cdot r
C ≠ f(“
”
r
A), then “
”
p \cdot r
C ∩ f(“
”
r
A) =  \emptyset  since Q(C) is a quotient, but
p \cdot r ∈ “
”
p \cdot r
C, and by hypothesis p \cdot r ∈ f(“
”
r
A). Contradiction. M
What is relevant for us, though, is that PER may be viewed also as an object of ω-
Set; this interprets the fact that T is a kind. The point is that the objects of PER form
a set and every set may be viewed as an ω-set:
Definition 3.1.4
Let ∆: Set  \rightarrow  ω-Set be given by ∆(S) = 〈S,  \Vdash S〉, where  \Vdash S = ω×S, that is, ∀n ∀s
n \Vdash S s (the full relation). The function ∆ is extended to a functor by setting ∆(f) = f,
the identity on morphism. M
In particular, set Mo = ∆(PER) ∈ ω-Set, the ω-set of types.
Remark 3.1.5 (For readers with some experience in Category Theory.)
ω-Set was equivalently defined in [Hyland 82] as the "~~separated objects" in his
Effective Topos, Eff. The category ω-Set has all finite limits and is a locally CCC
(see below for the cartesian closure). The embedding ∆ above preserves exponents
and limits. Moreover, one may embed ω-Set into Eff by a functor which preserves
limits and the lCCC structure.


<!-- Page 25 -->

By this, the present approach applies in a simple set-theoretic framework the
results in [Hyland 8 \triangleq ], [Pitts 8 \triangleq ], [Hyland Pitts 8 \triangleq ], [Carboni Freyd Scedrov 8
\triangleq ], and [Bainbridge
Freyd Scedrov Scott 8 \triangleq ]. The general treatment of models, as internal categories of
categories with finite limits, which was suggested by Moggi, is given in [Asperti Martini
89] and [Asperti Longo 90]. The elegant presentation in [Meseguer 88] compares various
approaches. We use here the fact that ω-Set is closed under products indexed over
itself and, in particular, we use the completeness of PER as an internal category. The
categorical products are exactly those naively defined below (to within isomorphism).
Both the explicit definition of PER as an internal category and the required (internal)
adjunctions are given in detail in [Longo Moggi 88], which is written also for non
category-theorists. (See also [Asperti Longo 90].) M
The reason for the next definitions is that we need to be able to give meaning,
over these structures, to kinds and types constructed as products, as expressed in rules
[KF Π] and [TF Π] in section 2.9. We take care of this point first, since it deals with the
crucial aspect of impredicativity in Quest. A first idea is to try to understand those
rather complex kinds and types as indexed products, in the naive sense of set theory.
Namely, given a set A and a function G: A  \rightarrow  Set, define as usual:
×a∈AG(a) = {f | f: A  \rightarrow  êa∈AG(a) and f(a) ∈ G(a)}.
This product wouldn't work, but the following simple restriction to realizable maps f,
will work.
Definition 3.1.6
Let 〈A,  \Vdash A〉 ∈ ω-Set and G: A  \rightarrow  ω-Set. Define the ω-set 〈Πa∈AG(a),  \Vdash ΠG〉 by
1) f ∈ Πa∈AG(a) iff f ∈ ×a∈AG(a) and ∃n. ∀a∈A. ∀p  \Vdash A a. n \cdot p  \Vdash G(a)
f(a),
2) n  \Vdash ΠG f iff ∀a∈A. ∀p  \Vdash A a. n \cdot p  \Vdash G(a) f(a) M
When the range of G is restricted to PER we obtain a product in PER:
Definition 3.1. \triangleq 
Let 〈A,  \Vdash A〉 ∈ ω-Set and G: A  \rightarrow  PER. Let Πa∈AG(a)PER ∈ PER be defined by
n (Πa∈AG(a)PER) m iff ∀a∈A. ∀p,q  \Vdash A a. n \cdot p G(a) m \cdot q M
A crucial property of ω-Set is that the products defined in 3.1.6 and 3.1. \triangleq  are
isomorphic for G: A  \rightarrow  PER.
Theorem 3.1.8 ([Bruce Longo 89])
Let 〈A,  \Vdash A〉 ∈ ω-Set and G: A  \rightarrow  PER. Then
〈Πa∈AIn(G(a)),  \Vdash ΠG〉 ≅ In(Πa∈AG(a)PER) in ω-Set.
Proof


<!-- Page 26 -->

Let  \Vdash ΠG be defined as in 3.1.6. We first prove that  \Vdash ΠG is a single-valued
relation. Assume that n  \Vdash ΠG f ∧ n  \Vdash ΠG h. We show that ∀a∈A. f(a) = h(a) and thus,
that f = h. By definition ∀a∈A. ∀p  \Vdash A a. n \cdot p  \Vdash G(a) f(a) ∧ n \cdot p  \Vdash G(a) h(a), and thus
f(a) = h(a) since, for all a, the relation  \Vdash G(a) is single valued (and any a in A is
realized by some natural number).
The isomorphism is given by J(f) = {n | n  \Vdash ΠG f}; thus the range of J is a
collection of disjoint sets in ω (equivalence classes). The isomorphism J and its
inverse are realized by the (indices for the) identity function. M
The existence in PER of "products" indexed over arbitrary ω-sets is a very relevant
fact. The point is to show that these object are real products, in a precise categorical
sense; this is hinted in remark 3.15. What we can do here, in our elementary
approach, is to use the idea in definition 3.1. \triangleq , in order to construct exponents as
particular cases of products.
Corollary 3.1.9
ω-Set and PER are CCC's. Moreover, the embedding In: PER  \rightarrow  ω-Set is full,
faithful and preserves the structure of CCC.
Proof
Observe that if G: A  \rightarrow  ω-Set is a constant function, G(a) = 〈B,  \Vdash B〉 for all a∈A,
say, then 〈Πa∈AG(a),  \Vdash ΠG〉 = 〈BA
,  \Vdash A \rightarrow B〉 is the exponent representing ω-Set[A,B]
in ω-Set. Clearly, in that case, n  \Vdash A \rightarrow B f iff ∀a∈A. ∀p  \Vdash A a. n \cdot p  \Vdash B f(a).
Products
are defined by using any bijective pairing functions from ω×ω to ω. Any singleton set
S gives a terminal object ∆(S). Eval and the currying operation Λ are defined as in Set
and are realized by (the indexes of) the universal function and the function s of the s-
m-n theorem. (The reader may check this as an exercise or see [Asperti Longo 90] for
details.)
The same argument applies to PER by taking, for A∈PER, G: A  \rightarrow  PER constant
in 3.1.8. (Just recall that PER may be viewed as the ω-set Mo = ∆(PER) and set 〈A,
 \Vdash A〉 = Mo.) Or also, by embedding PER in ω-Set by In, the corresponding ω-sets
give exponents, products, and terminal objects (up to isomorphisms), as In trivially
satisfies the properties stated. M
To clarify the construction, let's look more closely to exponent objects in PER.
Take say A \rightarrow B, that is, the representative of PER[A,B]. Then by definition each map
f∈PER[A,B] is uniquely associated with the equivalence class of its realizers, “
p”
A \rightarrow B
∈ A \rightarrow B, say, in the sense of 3.1.3.


<!-- Page 27 -->

It should be clear that the notion of realizer, or "type-free computation" computing
the typed function, is made possible by the underlying type-free universe, (ω,
.). As we
will discuss later, this gives mathematical meaning to the intended type-free
computations of a typed program after compilation. As for now, this feature of the
realizability model suggests a distinction between isomorphism in our categories,
which does not need to make sense in other frames (and is relevant for the intuition on
which our mathematical understanding is based):
Definition 3.1.10
An isomorphism f: A ≅ B in ω-Set is identical (or is an identical isomorphism) if
both f and its inverse f-1 are realized by the indices of the identity function. M
It is easy to rephrase this notion for objects in PER. Note though that A ≅ B in
PER via an identical isomorphism iff A = B (that is, A and B are equal).
In ω-Set, though, the isomorphism in 3.1.8 is identical (but it is not an identity).
Proposition 3.1.11
isomorphism.
Proof
In: PER  \rightarrow  ω -Set preserves products and exponents to within identical
Exercise. (The category oriented reader may check these preservation properties
also for equalizers, limits... and observe that they are generally not on the nose.) M
In summary, our types may be essentially viewed as kinds, by a very natural (and
strong) embedding. We applied this embedding in theorem 3.1.8, and gave there a
unified understanding of various products and arrows in the syntax. However,
theorem 3.1.8 really leads to much more than the cartesian closure of PER, which is
shown in corollary 3.1.9. In plain terms, 3.1.8 is the crucial step towards the meaning
of the second-order (polymorphic) types, namely of the types obtained by indexing a
collection of types over a kind, possibly over the collection of all types (an
impredicative construction).
### 3.2. Inclusion and power kinds
The purpose of this section is to set the basis for the semantics of the subkind and
subtype relations in Quest.
Definition 3.2.1 (subkinds)
Let 〈A,  \Vdash A〉, 〈B,  \Vdash B〉 ∈ ω-Set. Define:
〈A,  \Vdash A〉 ≤ 〈B,  \Vdash B〉 iff A ⊆ B and ∀a∈A.∀n. (n  \Vdash A a  \implies  n  \Vdash B a) M


<!-- Page 28 -->

The idea in this definition is that kinds may be related by the ≤ relation in ω-Set
only when they are actually subsets and when the realizability relation is defined in
accordance with this. Thus there is no need of coercions (equivalently, coercions are
just identity functions). Hence, the subsumption rule [KSub] for kinds is realized.
Subtyping will be interpreted in PER in a more subtle way, which allows a closer
look at the computational properties of the types of programs.
Definition 3.2.2 (subtypes)
Let A, B ∈ PER. Define:
A ≤ B iff ∀n,m. (n A m  \implies  n B m) M
Both ≤ relations in ω-Set and PER are reflexive and transitive. They are even
antisymmetric, because for 〈A,  \Vdash A〉, 〈B,  \Vdash B〉 ∈ ω-Set we have 〈A,  \Vdash A〉 = 〈B,  \Vdash B〉  \iff 
〈A,  \Vdash A〉 ≤ 〈B,  \Vdash B〉 ∧ 〈B,  \Vdash B〉 ≤ 〈A,  \Vdash A〉. Similarly, for C,D∈PER we have C = D  \iff 
C ≤ D ∧ D ≤ C.
The semantic notion of subtype we are using here is the one defined in [Bruce
Longo 89]. However, we differ from that approach for subkinds, in order to model the
strong relation we formalized in the syntax of Quest.
Clearly "≤" is a partial order which turns the objects of PER into an algebraic
complete lattice. When A and B are in PER and A ≤ B, then there is a coercer cA,B
from A to B. It is defined by the map cA,B: Q(A)  \rightarrow  Q(B) such that cA,B(“
”
n
A) = “
”
n
B,
which is computed by any index of the identity function. By definition, cA,B is
uniquely determined by A and B. (We may omit the subscripts, if there is no
ambiguity.)
Intuitively, given n such that nAn, the coercion cA,B takes its A-equivalence class,
“
”
n
A, to its (possibly larger) B-equivalence class, “
”
n
B. This is why cA,B, the coercion
morphism, is computed by all the indices of the identity function. Note that in general
“
”
n
A is smaller than “
”
n
B; they coincide just when Q(A) ⊆ Q(B), a special case of A ≤
B. Note also that for A,B∈PER, if In(A) ≤ In(B) regarded as ω-sets, then A ≤ B. The
reverse implication holds only when Q(A) ⊆ Q(B). The result is that, here, ≤ is used
with a slightly different meaning in the two categories, in contrast to the approach in
[Bruce Longo 89]. The advantage is given by the construction of a model of the current
rich kind and type theory.


<!-- Page 29 -->

The power operation is expressed in terms of quasi-functors, a weak notion of
categorical transformation between categories, widely used in several settings. (See
[Martini 88] for recent applications to the semantics of the λ-calculus.) This
interpretation is due to the blend of set-theoretical and categorical intuition at the base
of the current model of subtyping in a higher-order language. Quasi-functors take
morphisms to sets of morphisms which behave consistently with respect to
application (see below), and are such that the image of each identity map contains the
identity in the target category.
Definition 3.2.3
The power quasi-functor P : PER  \rightarrow  ω-Set is given by:
on objects: P A = 〈{B∈PER | B ≤ A},  \Vdash 〉, where ∀B ≤ A ∀n n  \Vdash  B;
on morphisms: for f: A \rightarrow C and p  \Vdash  f, define P p(f): P A \rightarrow P C pointwise by
mP p(f)(B)n iff ∃m',n'. m' B n' and m = p.m' and n = p.n'
Set then P (f) = {P p(f) | p  \Vdash  f }. M
For each f: A \rightarrow C and p  \Vdash  f, one has P p(f) ∈ ω-Set [P A,P C] since ω-Set[P A,P
C] = Set[P A,P C] in view of the full realizability relation given to the ω-set P C.
(More generally, each set-theoretic function which has as its target an object in the
range of ∆: Set  \rightarrow  ω-Set is realizable by all indices.)
It is also easy to observe that P (f•g) ⊆ P (f)•P (g) and id ∈ P (id) for f, g, and id in
the due types. This proves that P is a quasi-functor.
We claim that the interpretation of subtyping we are using, faithfully corresponds
to the intuitive semantics of subtyping (or is "compelling", as suggested in [Mitchell 88]
with reference to [Bruce Longo 89]).
Note first that the coercion cA,B in general is not a mono (or injective map) in
PER. It happens to be so only when Q(A) ⊆ Q(B), that is, when one also has In(A) ≤
In(B), as ω-sets. Indeed, the topos theoretic notion of subobject as mono from A to B,
given by Q(A) ⊆ Q(B), would not be able to give us the antimonotonicity of " \rightarrow " in
the first argument, and thus the simple but important theorems 3.4.1 and 3.4.2.
Moreover, in categories (and toposes) one usually works "to within
isomorphisms", while the programming understanding of subtypes and inheritance is
surely not "to within isomorphism". At most, the programming understanding is "to
within identical isomorphisms", as a general isomorphism may be a very complicated
program and is not likely to be computationally irrelevant.
In conclusion, we want a mathematical semantics which reflects the intuition of
the programmer, who views a subtype almost as a subset, but not exactly, as some
coercion may be allowed. Our model suggests what sort of coercions may be
generally natural: they must be computed by the type-free identical maps and
preserved by identical isomorphisms.


<!-- Page 30 -->

This interpretation explains why coercions may disappear in the description of the
programming language and why they do not show up at compile time, even though
they do not need to be exactly the identity. In our understanding, the compilation of a
typed program into its type-free version corresponds to the passage from a morphism
in the category of types or kinds, PER or ω-Set, to its type-free realizers. Type
coercions, in particular, are realized by identical computations.
Because of this interplay between sets, computations, and categories, the present
approach to subtypes is halfway between the set-theoretic notion of subset and the
category (or topos) theoretic subobjects. We claim that this is a suitable mathematical
understanding of the programmer's attitude.
We interpret now the formal equivalence of kinds and types as the equality in the
model. It is then easy to prove that the relations ≤ in 3.2.1-3.2.2, and the quasi-functor
P in 3.2.3, satisfy the applicable properties listed under "Kind inclusion" and "Type
inclusion", in section 2.9. We are then left with justifying subsumption and coercion,
described in section 2.5. We have already discussed the meaning of coercions; these
ideas will lead to the formal interpretation of Questc in part 4. Subsumption and Quest
will be dealt with in part 5. As already mentioned, recursive types and functions are
not considered.
### 3.3. Operator kinds
The formation, introduction, and elimination rules for operators ([KF Π], [TI Π], and
[TE Π]) are easily taken care of. Definition 3.1.6 tells us that we can form a kind, the ω-
set 〈Πa∈AG(a),  \Vdash ΠG〉, out of any kind (ω-set) 〈A,  \Vdash 〉 and any function G: A  \rightarrow  ω-Set
[KF Π]. By definition, the elements of 〈Πa∈AG(a),  \Vdash ΠG〉 are the (computable) functions
f such that, when fed with a∈A give as output elements f(a) of G(a). This is exactly
what rules [TI Π] and [TE Π] formalize.
Rule [T Π β] is understood in the model by the behavior of a λ-term as a function.
Indeed, [T Π η] stresses that in any model, functions are interpreted extensionally.
### 3.4. The kind of types
The lattice PER has ω = (ω, ω×ω) as largest element, that is, ω with the full
relation. Clearly, ω contains just one equivalence class, ω. Thus ω gives meaning to
Top, and ω to top. Moreover, the ω-set of all p.e.r.'s is given by Mo = P (ω).
Rule [TF Π] here is given meaning by definition 3.1. \triangleq . The interpretation is
apparently very simple, but there is a crucial asymmetry with respect to [KF Π]. Rule [KF
Π] has the structure:
kind kind
kind
Rule [TF Π], instead, looks like:
kind type


<!-- Page 31 -->

type
In particular, the kind on the left may be T, the kind of types.
This schema is the crucial type construction in explicit polymorphism. It is
impredicative in that, in order to know what types are, one must already know their
entire collection, T . ([Feferman 8 \triangleq , 88] and [Longo 88] provide further discussions.) This
peculiar type construction is reflected in the related rules.
In [VI Π] one allows the formation of terms where abstraction is not done with
respect to variables ranging over a type, as in the first-order case. Instead, they range
over a kind (possibly T, again). By this, it makes sense by rule [VE Π] to apply a term to
an element of a kind (possibly a type, and even the type of that very term). This is the
dimensional clash which is hard to justify mathematically, and is a central difficulty in
the semantics of polymorphism.
Theorem 3.1.8 relates [KF Π] and [TF Π] by telling us that they are interpreted by the
same construction, in the universe of ω-sets. This gives mathematical unity and clarity
of meaning. In particular, it says that the interpretations of terms constructed by [VI Π]
are going to be computable functions which may be fed with elements of an ω-set and
which then output a term of the expected type, as required by [VE Π] and as modeled in
the structure by definition 3.1.6.
Rule [TIncl Π] is validated by the following theorem.
Theorem 3.4.1
Let 〈A,  \Vdash A〉, 〈A',  \Vdash A'〉 ∈ ω-Set and G: A  \rightarrow  PER, G': A'  \rightarrow  PER. Assume A'≤A
in ω-Set and that ∀a'∈A', G(a') ≤ G'(a'), in PER. Then:
Πa∈AG(a) ≤ Πa'∈A'G'(a'), in PER.
Proof
Recall that done. M
n (Πa∈AG(a)PER) m iff ∀a∈A. ∀p,q  \Vdash A a. n \cdot p G(a) m \cdot q . Then
∀a∈A'. ∀p,q  \Vdash A' a. n \cdot p G(a) m \cdot q. Since n \cdot p G(a) m \cdot q implies n \cdot p G'(a) m \cdot q, we
are
With reference to the discussion on rules [KF Π] and [TF Π] above, a type formation
rule for products with the structure:
type type
type
would be a first-order rule and may be soundly interpreted over PER [Ehrhard 88].
Quest(c) has nothing of this structure for products, as it complicates typechecking and
compilation. An implicit use of it is the formal description and the semantics of
records given in [Bruce Longo 89]. In the current paper we could avoid any reference to
first-order constructs by coding record types in the second-order language (section
2.10). More on their interpretation will be given in section 3.5.


<!-- Page 32 -->

As for ordinary higher type functions, the interpretation of their rules, by corollary
3.1.9, is given as a special case of the meaning of the rules above, except for [TIncl  \rightarrow ],
since in this specific model types happen to be kinds (by the embedding In). The
arrow types are just degenerated products (that is, products defined by a constant
function, as in 3.1.9).
As an exercise, let's see what happens to the exponents in PER and their elements
(the equivalence classes). This may be done by a little theorem, which proves the
validity of rule [TIncl  \rightarrow ] in section 2.8.
Proposition 3.4.2
Let A, A',B, B'∈PER be such that A' ≤ A and B ≤ B'. Then A \rightarrow B ≤ A' \rightarrow B'. In
particular, for n (A \rightarrow B) n, “
”
n
A \rightarrow B ⊆ “
”
n
A' \rightarrow B'
Proof
n (A \rightarrow B) m  \iff  ∀p,q. (p A q  \implies  n \cdot p B m \cdot q )
 \implies  ∀p,q. (p A' q  \implies  n \cdot p B' m \cdot q ),
as p A' q  \implies  p A q  \implies  n \cdot p B m \cdot q  \implies  n \cdot p B' m \cdot q
 \iff  n (A' \rightarrow B') m
The rest is obvious. M
Proposition 3.4.2 gives the antimonotonicity of  \rightarrow  in its first argument, as
formalized in the rules of Quest [TIncl  \rightarrow ], and required by inheritance. Moreover, and
more related to the specific nature of this interpretation of  \rightarrow , proposition 3.4.2
reveals a nice interplay between the extensional meaning of programs and the
intensional nature of the underlying structure.
Indeed, typed programs are interpreted as extensional functions in their types, as
we identify each morphism in PER with the equivalence class of its realizers. That is,
if n  \Vdash A \rightarrow B f, then “
”
n
A \rightarrow B ∈ A \rightarrow B represents f∈PER[A,B] in the exponent object
A \rightarrow B. Assume for example that M: A \rightarrow B is interpreted by f∈PER[A,B]. (For the
moment we will call A both a type and that type's interpretation as a p.e.r.; see part 4
where the interpretation of terms and types is given.) In the assumption of the
proposition, f∈PER[A,B] and c(f)∈PER[A',B'] are distinct elements, and live in
different function spaces. The element c(f) is uniquely obtained by the coercion c,
which gives meaning to adjusting the types in M in order to obtain a program in
A'  \rightarrow  B'. Also, when viewed as equivalence classes of realizers, f and c(f) are different
sets of numbers.


<!-- Page 33 -->

However, the intended meaning of inheritance is that one should be able to run
any program in A \rightarrow B on terms of type A' also, as A' is included in A. When n  \Vdash A \rightarrow B
f, this is exactly what “
”
n
A \rightarrow B ⊆ “
”
n
A' \rightarrow B' expresses: any computation which realizes f
in the underlying type-free universe actually computes c(f) also. Of course, there may
be more programs for c(f), in particular if A' is strictly smaller than A. Thus, even
though f and c(f) are distinct maps (at least because they have different types) and
interpret different programs, their type-free computations are related by a meaningful
inclusion, namely “
”
n
A \rightarrow B ⊆ “
”
n
A' \rightarrow B' in this model.
This elegant interplay between the extensional collapse, which is the key step in
the hereditary construction of the types as partial equivalence relations, and the
intensional nature of computations is a fundamental feature of the realizability
models.
### 3.5. Records
Formally, there is nothing to be said about the semantics of records, as they are a
derived notion. However, we mention one crucial merit of the coding proposed and its
meaning.
Record types should not be understood simply as cartesian products. The main
reason is that the meaning of a record type R' with more fields than a record type R
(but where all the fields in R are in R') should be smaller than the meaning of R.
Indeed, R' contains fewer record relizers. This situation was obtained, say, in the PER
interpretation of [Bruce Longo 89] by understanding record types as indexed, first-order
products. That is, if I is a (finite) set of (semantic) labels, then Πi∈ΙAi would interpret
a record whose fields are interpreted by the Ai 's. By theorem 3.4.1, Πi∈ΙAi gives the
required contravariance in the meaning of records.
In the present approach, we can use the expressive power of Quest as a higher-
order language with a Top type, and model records with little effort. Record types are
coded as ordered tuples. Top is the last factor of the product and replaces missing
fields (with respect to the order), and by doing so it guarantees contravariance. This
intuition is precisely reflected in the model, by interpreting Top as the largest p.e.r..
Thus, any extension of a given record type by informative fields, that is, by fields
whose meaning is different from the full relation on ω, gives smaller p.e.r.'s.
4. Semantic interpretation of Questc
In this section we give the formal semantics of Questc over the ω-Set/PER model.
The basic idea, for the inductive definition, is to interpret type environments as ω-sets
with a realizability notion which codes pairs as elements of a dependent sum. In this
way, if for example E = ( \emptyset , y: B, x: A), then [E] contains all pairs:
<e,a> with e∈[ \emptyset , y: B] and a∈[ \emptyset , y: B  \vdash  A type]e


<!-- Page 34 -->

In this approach one has to interpret judgments, not just terms, as judgments contain
the required information to interpret (free) variables. For example, the variable x is
given meaning within the judgment E  \vdash  x:A, say, for E as above. In particular, its
interpretation [E  \vdash  x:A]e', for a fixed environment value e' = <e,a>∈[E], is the second
projection and gives a∈[ \emptyset , y: B  \vdash  A type]e. (See also [Scedrov 1988], [Luo 1988].) The
projection is clearly a realizable map, that is, it is computed by the index of a partial
recursive function. Note that the interpretation of closed terms depends on the
judgments they appear in, in particular on the types they are assigned to.
Moreover, the meaning of a judgment gives, simultaneously, the interpretation of
a construct (kind, type, or term) and makes a validity assertion; for example, it says
that a given term actually lives in the given type, under the given assumptions.
Kinds, types, and terms are interpreted as maps from the ω-set interpreting the
given environment to ω-Set, PER, and the intended type, respectively. As our
morphisms are extensional functions, the interpretation is uniquely determined by
their behavior on the elements of the environment. The indexes realizing these maps
may be computed by induction, using as base the indexes for the projection functions.
The crucial step is the interpretation of lambda abstraction and application for terms.
For example, given a realizer p for the map <e,A> ÷ïñ [E,X::K  \vdash  b:B]<e,A>, a realizer
for e ÷ïñ [E  \vdash  λ(X::K)b : Π(X::K)B]e is obtained by the recursive function s of the s-
m-n (or iteration) theorem, namely by an index for n ÷ïñ s(<p,n>), where s(<p,n>)(m)
= p(<n,m>). Similarly, any index for the universal partial recursive function gives the
realizers for an applicative term. We prefer to leave to the reader the intensional
details of the computations and focus on the extensional presentation of the
interpretation maps. These maps already require a fair amount of detail for a full
description and should not be further obscured by the explicit mention of the indexes
of the realizable functions.
Observe that, in a fixed environment, kinds are interpreted as ω-sets, while types
are p.e.r.'s. More precisely, operator kinds are functions which take an element of a
kind (possibly a type) as input and give an element of a kind (possibly a type) as
output. Also, these functions live in an ω-set, which is obtained as an indexed product
in the sense of 3.1.6.
As is common when dealing with CCC's, we make no distinction between an
exponent object, the p.e.r. A \rightarrow B, say, and the set of morphisms, PER[A,B], it
represents. Thus, the meaning of a term in PER[A,B], say, may be viewed either as a
function from the p.e.r. A to the p.e.r. B, or as the equivalence class of its realizers in
the p.e.r. A \rightarrow B (see also definition 4.1.1.(1) below). This poses no problem with
regard to ω-Set, since an exponent object is exactly an (ω-)set of (realizable)
functions, as in the category of sets.
### 4.1. Interpretation
We interpret, in order, environments, kinds, types, and terms.


<!-- Page 35 -->

Environments
E =  \emptyset  [E] = <{1},  \Vdash > where ∀n∈ω n  \Vdash  1
E = E', X::K A
[E] = <{<e,A> | e∈[E'] ∧ A∈[E'  \vdash  K kind]e},  \Vdash  E >
where <n,m>  \Vdash  E <e,A> iff n  \Vdash  E' e and m  \Vdash  [E'  \vdash  K kind]e
E = E', x:A [E] = <{<e,a> | e∈[E'] ∧ a∈[E'  \vdash  A type]e},  \Vdash  E >
where <n,m>  \Vdash  E <e,a> iff n  \Vdash  E' e and m  \Vdash  [E'  \vdash  A
type]e a
Kinds
 \vdash  E env ∀e∈[E]. [E  \vdash  T kind]e = M0
 \vdash  E env ∀e∈[E]. [E  \vdash  P (A) kind]e = P [E  \vdash A type]e
 \vdash  E env ∀e∈[E]. [E  \vdash  Π(X::K)L kind]e = 〈ΠA∈[E \vdash  K kind]eG(A),  \Vdash ΠG〉
where G: [E  \vdash  K kind]e  \rightarrow  ω-Set is given by
G(A) = [E,X::K  \vdash  L kind]<e,A>
 \vdash  E env ∀e∈[E]. [E  \vdash  λ(X::K)B :: Π(X::K)L] e ∈ ΠA∈[E  \vdash  K kind]e[E,X::K \vdash L
kind]<e,A>
such that ∀A∈[E  \vdash  K kind]e.
([E  \vdash  λ(X::K)B :: Π(X::K)L]e)(A) = [E,X::K  \vdash  B::L]<e,A>
∀e∈[E]. [E  \vdash  B(A) :: L{X←A}]e = ([E  \vdash  B:: Π(X::K)L]e)([E  \vdash 
 \vdash  E env A::K]e)
Types
 \vdash  E = E', Xn::Kn, E"
∀e = <...<en,An>,...>∈[E]. [E  \vdash  Xn::Kn]e = An∈ [E'  \vdash  Kn kind]en
 \vdash  E env ∀e∈[E]. [E  \vdash  Top type]e = ω = (ω, ω×ω)
 \vdash  E env type]<e,A>
∀e∈[E]. [E  \vdash  Π(X::K)B type]e = Π A ∈ [E  \vdash  K kind]e[E,X::K  \vdash  B


<!-- Page 36 -->

 \vdash  E env Terms
∀e∈[E]. [E  \vdash  A \rightarrow B type]e = [E  \vdash  A type]e  \rightarrow  [E  \vdash  B type]e
E = E', xn:An, E"
 \vdash  E env  \vdash  E env  \vdash  E env ∀e = <...<en,an>,...>∈[E]. [E  \vdash  xn:An]e = an∈ [E'  \vdash  An
type]en
∀e∈[E]. [E  \vdash  top:Top]e = ω
∀e∈[E]. [E  \vdash  cA,B(a):B]e = c[E  \vdash  A type]e,[E  \vdash  B type]e([E  \vdash  a:A]e)
∀e∈[E]. [E  \vdash  λ(X::K)b : Π(X::K)B]e
∈ ΠA∈[E \vdash  K kind]e[E,X::K  \vdash B type]<e,A>
such that ∀A∈[E \vdash  K kind]e.
([E  \vdash  λ(X::K)b : Π(X::K)B]e)(A) = [E,X::K  \vdash  b:B]<e,A>
∀e∈[E]. [E  \vdash  b(A) : B{X←A}]e = ([E  \vdash  b : Π(X::K)B]e)([E  \vdash  A
 \vdash  E env type]e)
 \vdash  E env ∀e∈[E]. [E  \vdash  λ(x:A)b : A \rightarrow B]e ∈ [E  \vdash  A type]e \rightarrow [E  \vdash  B type]e
such that ∀a∈[E  \vdash  A type]e.
([E  \vdash  λ(x:A)b : A \rightarrow B]e)(a) = [E,x:A  \vdash  b:B]<e,a>
 \vdash  E env ∀e∈[E]. [E  \vdash  b(a) : B]e = ([E  \vdash  b : A \rightarrow B]e)([E  \vdash a:A]e)
In view of the interpretation of kinds, types, and terms, the meaning of the
judgments is the obvious one. The :: and : relations go to ∈ for ω−sets and p.e.r.'s,
respectively; the relations <:: and <: are interpreted as subkind and subtype in ω−Set
and PER; finally, <::> and <:> are just equality.
Indeed, by induction on types and terms, one may check directly that this is a
good interpretation. In particular, one can check that all the given functions are
actually realized, as mentioned above, and hence that types and terms inhabit the
intended function and product spaces; see 4.1.2. (For example, [E  \vdash  λ(X::K)b :
Π(X::K)B]e is actually in ΠA∈[E \vdash  K kind]e[E,X::K  \vdash  B type]<e,A>.) However, this
also follows from general categorical facts, namely the cartesian closure of ω-Set and
the observation that PER, viewed as M0, is an internal CCC of ω-Set where the
internal product Π is right adjoint to the diagonal functor. (We obtain an internal
model of Girard's Fω; see [Asperti Longo 1990] where the general categorical meaning of
Fω is given.)
The next theorem, whose proof is left to the reader, summarizes all these facts,
and states the soundness of the interpretation. Before stating it, though, we set a better


<!-- Page 37 -->

foundation for the interplay of the interpretations of "terms as functions" and "terms
as equivalence classes". This is done by the following definition which extends the
applicative structure of (ω,
 \cdot ) to equivalence classes, and also to the application of an
equivalence class to an element of an ω-set (cf. 3.1. \triangleq ).
Definition 4.1.1
1 - Let A and B be p.e.r.'s. Define then, for n(A \rightarrow B)n and mAm,
“
”
“
”
“
”
n
A \rightarrow B \cdot 
m
A =
n.m
B
2 - Let 〈K,  \Vdash K〉 ∈ ω-Set and G: K  \rightarrow  PER. Set, for short, Π = ΠA∈KG(A)PER and
define, for nΠn, A∈K, and p  \Vdash  A:
“
”
n
Π \cdot A = “
n.p”
G(A)
(Note that " \cdot " : Π×Κ  \rightarrow  êA∈KG(A) depends on K and G.) This is well defined as
“
n.p”
G(A) does not depend on the choice of the number p, which realizes A. M
By this explicit reconstruction of the applicative behavior, one may more clearly
understand equivalence classes in the p.e.r.'s A \rightarrow B and ΠA \notin KG(A)PER as functions in
the due types.
Theorem 4.1.2
 \vdash  E env  \implies  [E] is a well-defined ω-set
E  \vdash  K kind E  \vdash  A::K E  \vdash  A type E  \vdash  a:A  \implies   \implies   \implies   \implies  ∀e∈[E].
[E  \vdash  K kind]e is a well-defined ω-set
∀e∈[E]. [E  \vdash  A::K]e ∈ [E  \vdash  K kind]e
∀e∈[E]. [E  \vdash  A type]e ∈ M0
∀e∈[E]. [E  \vdash  a:A]e ∈ [E  \vdash  A type]e
E  \vdash  K <:: L E  \vdash  A <: B  \implies   \implies  ∀e∈[E]. [E  \vdash  K kind]e ≤ [E  \vdash  L kind]e in ω-Set
∀e∈[E]. [E  \vdash  A type]e ≤ [E  \vdash  B type]e in PER
E  \vdash  K <::> L E  \vdash  A <:> B E  \vdash  a  \cong  b  \implies   \implies   \implies  ∀e∈[E]. [E  \vdash  K
kind]e = [E  \vdash  L kind]e
∀e∈[E]. [E  \vdash  A type]e = [E  \vdash  B type]e
∀e∈[E]. [E  \vdash  a:A]e = [E  \vdash  b:A]e M
### 4.2. Emulating coercions by bounded quantification
In Questc and in its current interpretation we have no subsumption, but instead we
have coercions. This means that programs of the form
(λ(x:B)d)(a) where a:A<:B (with A≠B) (1)
are not legal: an explicit coercion has to be applied, as in
(λ(x:B)d)(cA,B(a)) (2)


<!-- Page 38 -->

In this latter case, one may avoid both subsumption and coercions and recast (1)
via an additional bounded quantifier:
(λ(X<: B)λ(x:X)d)(A)(a) (3)
It is clear that (3) has the same effect as (1) or as (2), since this is how (1) can be
correctly expressed in our current framework, by coercions. The fact that (2) and (3)
are equivalent is a fairly deep property of the semantics, relating a bounded quantifier
to a coercion. In general, this is not derivable from the syntax.
The following theorem states that, semantically, coercions can be removed in
favor of bounded quantifiers.
Recall that E  \vdash a : A ∧ E  \vdash A <: B  \implies  E  \vdash cA,B(a) : B.
Theorem 4.2.1
Assume that E  \vdash  d : D, E  \vdash  a : A and E  \vdash  A <: B. Then, in PER one has
(λ(X<:B)λ(x:X)d)(A)(a) = (λ(x:B)d)(cA,B(a))
Proof
For simplicity, we fix an environment e and identify types A, B, and D with their
meanings as p.e.r. in e.
Set Π = ΠX≤BX \rightarrow D and let “
”
n
Π = [ E  \vdash  (λ(X<:B)λ(x:X)d) : Π(X<:B)(X \rightarrow D) ]e ∈
Π. Then “
”
n
Π \cdot C = “
n.p”
C \rightarrow D for any C, such that E  \vdash  C <: B, and any p, since any
number p realizes C, when C ≤ B, by definition of the power quasi-functor.
Let now m be such that [E  \vdash  a : A]e =
“
”
m
A. Then cA,B(“
”
m
A) = “
”
m
B and:
[ E  \vdash  (λ(X<:B)λ(x:X)d)(A)(a) : D ]e
“
”
=
n
Π \cdot A \cdot “m
”
“
A=
n.p”
A \rightarrow D \cdot “m
”
“
”
A=
n.p.m
D
“
=
n.p”
B \rightarrow D \cdot “m
”
B where n.p(B \rightarrow D)n.p by 4.1.1(1)
“
”
=
n
Π \cdot B \cdot “m
”
B by 4.1.1(2)
= [ E  \vdash  (λ(X<:B)λ(x:X)d)(B)cA,B(a) : D ]e
= [ E  \vdash  (λ(x:B)d)cA,B(a) : D ]e by the syntax. M
In Questc, we dropped the subsumption rule in favor of coercions. However, there
is also a proof-theoretic reason to warn the programmer about the use of subsumption
in connection with (η); namely, the equational system of typed terms would not be
Church-Rosser any more (with respect to the obvious reduction rules). Consider say:
λ(x:A)(λ(y:B)e)x (with x  \notin  FV(λ(y:B)e))
where x is not free in λ(y:B)e, and let A <: B.
In the presence of subsumption, this program would type-check, for any e and C
such that e:C. However,
λ(x:A)(λ(y:B)e)x Òñ λ(y:B)e : B  \rightarrow  C by (η)
λ(x:A)(λ(y:B)e)x Òñ λ(x:A)e : A  \rightarrow  C by (β)
and confluence would be lost. Because of this, we abandon (η) in part 5.
In Questc, the program one has in mind when writing λ(x:A)(λ(y:B)e)x, is actually
described by the polymorphic term:


<!-- Page 39 -->

λ(x:A)(λ(X<:B) λ(y:X) e)(A)(x)
which yields confluent reductions.
For this reason, (η) is adopted in Quest as an equality rule, but not as a
computation rule.
5. Semantic interpretation of Quest
In this section we model the original version of Quest, namely the language based
on the subsumption rule [TSub / Quest] of section 2.9, instead of on coercions.
Subsumption is important for at least two reasons. First, programming with
explicit coercions becomes too cumbersome; much of the appeal of subtyping has to
do with the flexibility and compactness provided by subsumption. Second,
subsumption is intended not as an arbitrary coercion, but as a coercion that performs
no work; this is essential for capturing the flavor of object-oriented programming,
where subsumption is used freely as a way of viewing objects as members of different
types.
Hence we feel we are justified in presenting more complex semantic techniques in
order to give a faithful representation of subsumption.
Let (D,
. ) be a model of type-free lambda calculus. The construction of the
categories D D D D-Set and PERD D D D over (D,
. ) works similarly. Indeed, all the work carried
on so far can be easily generalized to any (possibly partial) Combinatory Algebra or
model of Combinatory Logic. In view of the relevance of Kleene's realizability
interpretation of Intuitionistic Logic for these models, it is fair to call "realizability
structures" the categories D D D D-Set and PERD D D D over a Combinatory Algebra (D,
. ). As
already mentioned, we preferred (ω,
 \cdot ) as it is more directly related to Kleene's work
and because of the immediate intuitive appeal of classical recursion theory. However,
we now need to be able to give meaning to type-free terms, which cannot be done
over (ω,
 \cdot ). For this purpose, we work over an arbitrary λ-model: that is, an
applicative structure (D,
. ) with an interpretation D[ - ] of λ-terms defined, say, as in
[Hindley Longo 80] or [Barendregt 84].
The interpretation of Quest is given in two steps. First we translate typed terms
into terms of the type-free calculus, by "erasing-types". We add to the latter only a
constant symbol "top", in order to take care of the corresponding constant in Quest.
In the second step, we use the meaning of the erased terms to interpret typed
terms. Environments, kinds, and types will be interpreted as in Questc, except for an
"isomorphic change" in the interpretation of product types. As for types in particular,
this interpretation is possible since, in view of our formal definition of subkinds and
of its semantics, we had no kind coercions even in Questc, but just type coercions.


<!-- Page 40 -->

Terms may still be understood as morphisms, in the due types. We already used
the identification of morphisms with the equivalence classes of their realizers. In the
interpretation of Quest we exploit this correspondence and interpret typed terms
directly as equivalence classes, with no ambiguity.
Briefly, for each environment e = <...<en,an>,...> ∈ [E] we choose an environment
map se: Var  \rightarrow  D which picks up an element of the equivalence class an. Then, by
using these environment maps, we interpret a typed term as the equivalence class
which contains the interpretation of its erasure.
The interpretation will not depend on the particular choice of the environment
map.
### 5.1. Preliminaries and structures
The categories D D D D-Set and PERD D D D over (D,
. ) are defined exactly as ω-Set and
PERω over (ω,
 \cdot ), in 3.1.1 and 3.1.2. However, their use in the semantics of Quest
will be slightly changed in a crucial point. Second-order impredicative quantification
will not be interpreted exactly by the set-theoretic indexed product of realizable
functions, as in 3.1. \triangleq . We will use instead an isomorphic, but not identical,
interpretation of this quantification by p.e.r.'s obtained as a straightforward set-
theoretic intersection. This is made possible by the following simple, but fundamental
theorem, which establishes a connection between the previous interpretation of
higher-order quantification and the one given in [Girard  \triangleq 2] and [Troelstra  \triangleq 3]. It was first
suggested by Moggi and actually started most of the recent work on the semantics of
polymorphism, by suggesting that Girard's model could be given a relevant
categorical explanation. (See remark 3.1.5.) We use it here as a tool for our semantic
interpretation of Quest. We report its proof since it matters for our purposes, as we
point out in remark 5.1.2. Note first that, if {Ai}i∈I is a collection of p.e.r.'s, then
ëi∈IAi is also a p.e.r. by
n(ëi∈IAi)m iff n Ai m for all i∈I
Theorem 5.1.1
Let 〈A,  \Vdash A〉 ∈ D D D D-Set be such that  \Vdash A = D×A and let G: A  \rightarrow  PERD D D D. Then:
(Πa∈AG(a))PERD D D D
≅ ëa∈AG(a) in PERD D D D.
Proof ([Longo Moggi 88])
Let S = ëa∈AG(a) ∈ PERD D D D. By definition both Πa∈AG(a)PERD D D D and S are in
PERD D D D. Thus we need to define a bijection H: S  \rightarrow  Πa∈AG(a)PERD D D D and prove that it is
realized with its inverse.
Let H(“
”
n
S) = λa∈A.“
”
n
G(a). Clearly, H(“
”
n
S) ∈ Πa∈AG(a) and H is well defined,
since “
”
“
”
n
S =
m
S implies, n G(a) m for all a∈A, and hence “
”
“
”
n
G(a) =
m
G(a).
Consider now the combinator k such that k.p.q = p, for all p, q ∈ D. Then k.n
realizes H(“
”
n
S), since
∀a∈A. ∀q  \Vdash A a. k.n.q = n∈“
”
n
G(a) = H(“
”
n
S)(a),


<!-- Page 41 -->

and k realizes H. It is easy to observe that H is injective. Let us prove that H is
surjective.
If h ∈ Πa∈AG(a), then by definition, ∃m  \Vdash ΠG h; that is,
∃m. ∀a∈A. ∀q  \Vdash A a. m.q  \Vdash G(a) h(a) or, equivalently,
∃m. ∀a∈A. ∀q∈D. h(a) = “
m.q”
G(a), as  \Vdash A = D×A
Fix now an element 0 of D. Then, for n = m.0, we have ∀a∈A. n G(a) n, that is, n S n.
In conclusion, ∀a∈A. H(“
”
n
S)(a) = “
”
n
G(a) = h(a), that is, H(“
”
n
S) = h. Therefore H-1
exists and it is realized by any p ∈ D such that p.m= m.0, for all m ∈ D. M
Remark 5.1.2
The key idea in the proof consists in defining the applicative or functional
behavior of each equivalence class “
”
n
S, say, in S = ëa∈AG(a) ∈ PERD D D D, by setting
“
”
“
”
n
S \cdot a =
n
G(a)
This is how, to within isomorphism, “
”
n
S defines a function in Πa∈AG(a). Observe
that, when the isomorphism is given by the "constant-constructor" combinator k, the
proof relates this notion of application to the application “
”
“
n
Π \cdot a =
n.p”
G(a), for p  \Vdash A a,
as defined in 4.1.1. Indeed, “
n.p”
G(a) is constant with respect to p, under the
assumption  \Vdash A = D×A in 5.1.1. The next proposition shows that this assumption is
satisfied by the D-sets we are interested in: that is, by the definable ones, in the
language of Quest. M
Proposition 5.1.3
with  \Vdash A = D×A.
Proof
Let  \vdash  E env and E  \vdash  K kind. Then, for all e∈[E], [E  \vdash  K kind]e is a D-set 〈A,  \Vdash A〉
This is clearly true for the base of the induction, in view of the interpretation of T
and P (C), for any type C. (Recall that one even has T = P (Top) ). Consider now E  \vdash 
Π(X::K)L kind. Then:
∀e∈[E]. [E  \vdash  Π(X::K)L kind]e = 〈 ΠA∈[E \vdash  K kind]e[E,X::K \vdash L kind]<e,A>,
 \Vdash ΠG〉,
where G(A) = [E,X::K \vdash L kind]<e,A>. By induction, just assume that, for all e and A,
the D-set L(e,A) = [E,X::K \vdash L kind]<e,A> has the full  \Vdash L relation. Then any set
theoretic function f in ×A∈[E \vdash  K kind]e[E,X::K \vdash L kind]<e,A> is realized by any n ∈ D,
since one always has n.p \Vdash L f(A), no matter which A∈[E \vdash  K kind]e and p are taken.
M


<!-- Page 42 -->

Remark 5.1.4 (For readers with some experience in Category Theory.)
Continuing from remark 3.1.5. In [Hyland 8 \triangleq ] and [Longo Moggi 88], the existence of
a (internal) right adjoint to the diagonal functor, that is, the small completeness of
PER in the Effective Topos or in ω-Set, is shown by taking exactly the intersection as
product (see [Asperti Longo 90] for details). This fully justifies the interpretation below
of second-order impredicative types as intersections. M
5.2 Interpretation [ [ [ [ - ] ] ] ]'
We now translate typed terms into terms of the type-free calculus, by erasing all
type information. The type-free λ-calculus is extended by a constant symbol, top.
Definition 5.2.1
The translation map erase from typed terms into type-free terms is defined by
induction on the structure of terms:
erase(x) = x
erase(top) = top
erase(λ(x:A)b) = λx. erase(b)
erase(b(a)) = erase(b)erase(a)
erase(λ(X::K)b) = erase(b)
erase(b(A)) = erase(b) M
With the preliminaries above, it is now straightforward to implement our idea: a
typed term is interpreted by the equivalence class of its erasure, with respect to its
type as p.e.r.. We then need to show that this interpretation is sound. Indeed, this
interpretation generalizes a theorem stated in [Mitchell 86] and tidily relates to the
alternative approach to the semantics of the subsumption rule [TSub / Quest] in [Bruce
Longo 89]. Observe that this interpretation, in contrast to the early attempt in [Bruce
Longo 89], is direct. This is made possible by the use of theorem 5.1.1, since by erasure
the meaning of a second-order typed term becomes an element of the intersection of
all the types which form its range. For example, the polymorphic identity function
λ(X::T) λ(x:X) x : Π(X::T) (X \rightarrow X) will be interpreted as the equivalence class of the
type-free identity λx.x, which happens to live in A \rightarrow A, for any type A.
Note finally that, since the interpretations of type-free terms are elements of D,
while the elements of types as p.e.r.'s are equivalence classes, we need a choice map
to obtain an environment for type-free terms from an environment for typed ones.
This is done by the following definition.


<!-- Page 43 -->

Definition 5.2.2
Given E = E', xn:An, E" and e = <...<en,an>,...> ∈ [E], fix se: Var  \rightarrow  D such that
se(xn) ∈ an ∈ [E'  \vdash  An type]'en, where [E] is defined as in section 4.1, and [E'  \vdash  An
type]'en is the interpretation of types given below. M
Note that se is defined only on term variables and gives no meaning to X::K. The
interpretation below will not depend on the choice of se. Recall that D[ - ] is the
interpretation of type-free terms in (D,
. ).
Environments
[E]' coincides with [E] for Questc
Kinds No change.
Types No change, except for:
 \vdash  E env ∀e∈[E]. [ E  \vdash  Π(X::K)B type]'e = ë A ∈ [E  \vdash  K kind]'e[E,X::K \vdash B
type]'<e,A>
Terms
 \vdash  E env ∀e∈[E]'. [E  \vdash  a : A]'e = “ D[erase(a)]se
”
[E  \vdash  A type]'e
Since higher-order quantification is interpreted as intersection, by an even easier
proof than for Questc, we have:
Lemma 5.2.3
E  \vdash  A<:B implies ∀e∈[E]'. [E  \vdash  A type]'e ≤ [E  \vdash  B type]'e M
The following theorem proves the soundness of the interpretation.
Proposition 5.2.4
D D D D-Set and PERD D D D.
Proof
The interpretation [ ]' is a well-defined meaning for kinds, types, and terms over
We need to check only the result for terms, since kinds pose no problem, and there
has been enough discussion concerning types and the use of intersection as product.
Recall from proposition 5.1.3 that [E \vdash  K kind]'e is a D-set with the full relation.


<!-- Page 44 -->

Thus we show by induction on the derivation that, for each E  \vdash  a : A,
D[erase(a)]se is in the domain of [E  \vdash  A type]'e and that it has the correct functional
behavior.
Case E = E', xn:An, E"  \vdash  xn:An
 \vdash  E env ∀e∈[E]'. [E  \vdash  xn:An]'e = “
se(xn)”
[E  \vdash  A
type]'e
n
n
which corresponds to
∀e = <...<en,an>,...>∈[E]. [E  \vdash  xn:An]'e = an∈ [E \vdash An type]'en
Case E  \vdash  top:Top
Just recall that ω is the only element of ω.
Case E  \vdash  b(a) : B
∀e∈[E]'. [E  \vdash  b(a) : B]'e = “D[erase(ba)]se
”
[E  \vdash  B type]'e
=
“D[erase(b)erase(a)]se
”
[E  \vdash  B type]'e
= (“D[erase(b)]se
”
[E  \vdash  A \rightarrow B type]'e) . (“D[erase(a)]se
”
[E  \vdash  A type]'e)
= ([E  \vdash  b : A \rightarrow B]'e) . ([E  \vdash a:A]'e)
where application between equivalence classes is defined as in 4.1.1.
This simultaneously proves that [ - ]' decomposes soundly and that D[erase(ba)]se is
in dom([E  \vdash  B type]'e).
Case E  \vdash  λ(x:A)b : A \rightarrow B
∀e∈[E]'. [E  \vdash  λ(x:A)b : A \rightarrow B]'e = “D[λx.erase(b)]se
”
[E  \vdash  A \rightarrow B type]'e
which is well defined because by induction, from the semantics of E, x:A  \vdash  b : B, one
has for all n∈D :
n ([E  \vdash  A type]'e) n  \implies  (D[erase(b)]se[n/x]) is in dom([E  \vdash  B type]'e)
Thus D[λx.erase(b)]se is in dom([E  \vdash  A \rightarrow B type]'e), by virtue of the familiar
substitution lemmas in the type-free model (D,
.
, D[ - ]). (See [Barendregt 84].)
Case E  \vdash  λ(X::K)b : Π(X::K)B
∀e∈[E]'. [E  \vdash  λ(X::K)b : Π(X::K)B]'e = “D[erase(b)]se
”
Σ
where Σ = ∩A::K{[E  \vdash  B{X←A} type]'e}. (Note that, by the usual substitution
techniques, one has [E  \vdash  B{X←A} type]'e = [E,X::K  \vdash  B type]'<e,A>, where we keep
identifying the semantic and the syntactic type A by an abuse of language.) This is
well defined just as before, since, by induction, one has:
E,X::K  \vdash  b : B implies D[erase(b)]se is in dom([E,X::K  \vdash  B type]'e)
However, in contrast to the previous case, D[erase(b)]se does not depend on X::K
while B and its semantics do. Exactly because of this, for all types A one has
D[erase(b)]se is in dom([E  \vdash  B{X←A} type]'e)
and thus D[erase(b)]se is in dom(Σ). The next case describes also the applicative
behavior of [E  \vdash  λ(X::K)b : Π(X::K)B]'e.
Case E  \vdash  c(A) : B{X←A}
∀e∈[E]'. [E  \vdash  c(A) : B{X←A}]'e = “D[erase(c)]se
”
[E  \vdash  B{X←A} type]'e


<!-- Page 45 -->

by the definition of erase. Observe now that one must have E  \vdash  c : Π(X::K)B. By
setting
Σ = ∩A::K{[E  \vdash  B{X←A} type]'e}
by the previous case and the definition of erase, one has
∀e∈[E]'. [E  \vdash  c : Π(X::K)B]'e = “D[erase(c)]se
”
Σ in dom(Σ)
Thus, for all A D[erase(c)]se is in dom([E  \vdash  B{X←A} type]'e).
By this and by the definition of application of an intersection class to a p.e.r., given in
5.1.2, compute
D[erase(c)]se
”
[E  \vdash  B{X←A} type]'e = (“D[erase(c)]se
”
Σ) . ([E  \vdash  A type]'e)
= ([E  \vdash  c:Π(X::K)B]'e) . ([E  \vdash  A type]'e) M
We have also proved:
Corollary 5.2.5
If  \vdash  E env, then ∀e∈[E]. [E  \vdash  a : A]'e ∈ [E  \vdash  A type]'e. M
It is a minor variant of the work done for Questc to check fully that we provided
an interpretation for Quest (that is, that the analogue of theorem 4.1.2 holds for
Quest). The crucial point is the validity of the subsumption rule:
E  \vdash  a : A E  \vdash  A <: B
E  \vdash  a : B
This rule is valid simply because the interpretation of the term a, say, comes with
the meaning of the entire judgment E  \vdash  a : A or E  \vdash  a : B. We gave this meaning in
such a way that it automatically coerces a to B in the semantics when interpreting E  \vdash 
a : B. Indeed, the meaning of E  \vdash  a : A is an equivalence class in the p.e.r. [E  \vdash  A
type]'e (together with the assertion that it actually belongs to the class), while the
meaning of [E  \vdash a:B]'e is an element of the p.e.r. [E  \vdash  B type]'e, which is in general a
larger equivalence class.
It is worth noticing the essential role of the interpretation of polymorphic types as
intersections. The isomorphism between product and intersection in 5.1.1 is the core
of this interpretation. (See the last two cases in 5.2.1.) It says that type erasing does
not affect the meaning of polymorphic terms, modulo equivalence classes, and
reduces the entire challenging business of how to apply a term to a type, to a simple
type coercion in the model. That is, “
”
n
S \cdot A = “
”
n
G(A), which interprets the polymorphic
application for S = ëA∈KG(A) (see 5.1.2), corresponds to coercing “
”
n
S to the
generally larger equivalence class “
”
n
G(A).
This has a clear mathematical and computational meaning. Mathematically, it
derives from the fact that the maps from any D-set with the full realizability relation
to a p.e.r. are constant functions. (See [Longo Moggi 88], or prove it for exercise.) This


<!-- Page 46 -->

is a simple feature inherited from a deep fact: the validity of the Uniformity Principle
in the Realizability Universe, which is the categorical background of this construction
[Longo 88]. Computationally, it says that at run time we disregard types, or that
computations are type-free, in particular the computation of a polymorphic term.
However, given a computation n of type ëA∈KG(A), it happens that n is equivalent to
more computations when updated to type A: namely, all those in “
”
n
G(A).
In [Bruce Longo 89] yet another interpretation of Fun, the progenitor of Quest, is
given. The idea, in that paper, is to use the interpretation of the language with
coercions in order to give meaning to the one without coercions. This is based on a
series of theorems which relate abbreviated terms (that is, terms where all coercions
are erased) to their fattenings (that is, terms where coercions are put back in place).
More precisely, in our language, given E  \vdash c a : A, a judgment in Questc, abbrev(a) is
obtained by erasing all coercions. Then, for E  \vdash  b : B in Quest, b' is a fattening when
abbrev(b') = b. The BL-interpretation of the judgment E  \vdash  a : A in Quest, is given by
setting:
BL[E  \vdash  a : A]e = [E  \vdash c a' : A]e
where [E  \vdash c a' : A]e is the semantics in part 4, for a fattening a' of a.
With some work, [Bruce Longo 89] showed that this is well defined. Indeed, it
coincides with our current interpretation [ - ]'. In other words, by the results in [Bruce
Longo 89] and some further work, we claim that, given a model of the type-free λ-
calculus and the realizability structures over it as models of Quest, one has:
BL[E  \vdash  a : A]e = [E  \vdash  a : A]'e
Observe finally that this interpretation is "coherent", in the sense of [Curien Ghelli 89],
since by definition it depends only on the proved judgment and not its derivation.
More generally, the model satisfies the conditions in the coherence theorem in [Curien
Ghelli 89].
6. Conclusions
We have described a formal system, which can be considered the kernel of the
Quest language, and we have investigated a particularly attractive approach to its
semantics. The formal system requires a lot of semantics models, probably more than
any previous typed system. Fortunately, PER models promise to satisfy all the
required features, and more (e.g. dependent types). More work needs to be done both
on the syntactic side, studying the properties and the degree of completeness of the
formal system, and on the semantic side, mostly with respect to recursion and
recursive types.


<!-- Page 47 -->

## Acknowledgements
We would like to thank Roberto Amadio and Kim Bruce. Working jointly and in
parallel with them has provided us with a permanent source of ideas and inspiration.
The many discussions with John Mitchell and P.-L. Curien have been essential for
this work. We also thank Martín Abadi, Simone Martini, and Andre Scedrov for
important suggestions, and Narciso Marti-Oliet for careful technical proofreading.
Aspects of the formal system have been inspired by, and are still under investigation
by many of the authors above.


<!-- Page 48 -->

## References
[Abadi Plotkin 90] M.Abadi, G.D.Plotkin: A Per model of polymorphism and recursive types, LICS
'90.
[Amadio 89] R.Amadio: Recursion over realizability structures, Information and Computation, to
appear.
[Amadio 89a] R.Amadio: Formal theories of inheritance for typed functional languages, Note
interne TR 28/89, Dipartimento di Informatica, Universit \langle  di Pisa.
[Asperti Longo 91] A.Asperti, G.Longo: Categories, types and structures: an introduction to
category theory for the working computer scientist, M.I.T. Press, to appear.
[Asperti Martini 89] A.Asperti, S.Martini: Categorical models of polymorphism, Note interne,
Dipartimento di Informatica, Universit \langle  di Pisa.
[Bainbridge Freyd Scedrov Scott 8 \triangleq ] E.S.Bainbridge, P.J.Freyd, A.Scedrov, P.J.Scott: Functorial
polymorphism, preliminary report, Proc. of the Programming Institute on Logical Foundations
of Functional Programming, Austin, Texas, June 198 \triangleq , and T.C.S. vol.  \triangleq 0, pp. 35-64, 1990.
[Barendregt 84] H. Barendregt: The lambda calculus; its syntax and semantics, Revised and
expanded edition, North Holland.
[Breazu-Tannen Coquand Gunter Scedrov 89] V.Breazu-Tannen, T.Coquand, C.Gunter, A.Scedrov:
Inheritance and explicit coercion, Proc. of the Fourth Annual Symposium on Logic in Computer
Science, 1989.
[Bruce Longo 89] K.Bruce, G.Longo: Modest models of Records, Inheritance and Bounded
Quantification, Information and Computation, to appear. (Preliminary version: CMU Report CS-
88-126, Proceedings of LICS '88, Edinburgh, pp. 38-50).
[Carboni Freyd Scedrov 8 \triangleq ] A.Carboni, P.J.Freyd, A.Scedrov: A categorical approach to
realizability and polymorphic types, Proc. of the Third Symposium on Mathematical
Foundations of Programming Language Semantics, New Orleans, to appear.
[Cardelli 88] L.Cardelli: A semantics of multiple inheritance, in Information and Computation  \triangleq 6, pp
138-164, 1988.
[Cardelli 89] L.Cardelli: Typeful programming, Lecture Notes for the IFIP Advanced Seminar on
Formal Methods in Programming Language Semantics, Rio de Janeiro, Brazil, 1989. SRC Report
#45, Digital Equipment Corporation, 1989.
[Cardelli Donahue Glassman Jordan Kalsow Nelson 88] L.Cardelli, J.Donahue, L.Glassman, M.Jordan,
B.Kalsow, G.Nelson: Modula-3 report, Research Report n.31, DEC Systems Research Center,
Sep. 1988.
[Cardelli Mitchell 89] L.Cardelli, J.C.Mitchell: Operations on records, Proc. of the Fifth Conference
on Mathematical Foundations of Programming Language Semantics, New Orleans, 1989, to
apppear.
[Cardelli Wegner 85] L.Cardelli, P.Wegner: On understanding types, data abstraction and
polymorphism, Computing Surveys, Vol 1 \triangleq  n. 4, pp 4 \triangleq 1-522, December 1985.
[Cook Hill Canning 90] W.Cook, W.Hill, P.Canning: Inheritance is not subtyping, Proceedings of
POPL'90, San Francisco.
[Curien Ghelli 90] P.L. Curien, G. Ghelli: Coherence of subsumption, to appear.
[Ehrhard 88] T.Ehrhard: A Categorical Semantics of Constructions Proceedings of LICS'88,
Edinburgh.


<!-- Page 49 -->

[Fairbairn 89] J. Fairbairn: Some types with inclusion properties in ∀, î î î îï ï ï ïñ ñ ñ ñ
, µ, Technical Report No.
1 \triangleq 1, University of Cambridge, Computer Laboratory.
[Feferman 8 \triangleq ] S. Feferman: Weyl Vindicated: Das Kontinuum,  \triangleq 0 Years Later, preprint, Stanford
University (Proceedings of the Cesena Conference on Logic and Philosophy of Science, to appear).
[Feferman 88] S.Feferman: Polymorphic typed lambda-calculi in a type-free axiomatic framework,
Dept. of Mathematics, Journal of the ACM 151, 185, 30, 1 January.
[Freyd Mulry Rosolini Scott 90] P.J.Freyd, P.Mulry, G.Rosolini, D.Scott: Domains in Per, LICS '90.
[Girard  \triangleq 2] J-Y.Girard: Interprétation fonctionelle et élimination des coupures dans l'arithmétique
d'ordre supérieur, Thèse de doctorat d'état, Université Paris VII, 19 \triangleq 2.
[Hindley Longo 80] R. Hindley, G. Longo: Lambda-calculus models and extensionality Zeit. Math.
Logik Grund. Math. n. 2, Vol. 26 (289-310).
[Hyland 82] M.Hyland: The effective topos, in The Brower Symposium, Troelstra and Van Dalen eds.,
North-Holland 1982.
[Hyland 8 \triangleq ] M.Hyland: A small complete category, lecture delivered at the conference: Church's
Thesis after 50 years, Zeiss (NL), June 1986. Annals of Pure and Applied Logic, 40, 1988.
[Hyland Pitts 8 \triangleq ] J.M.E.Hyland, A.M.Pitts: The theory of constructions: categorical semantics and
topos-theoretic models, in Categories in Computer Science and Logic (Proc. Boulder '8 \triangleq ),
Contemporary Math., Amer. Math. Soc., Providence RI.
[Longo 88] G.Longo: Some aspects of impredicativity: notes on Weyl's philosophy of mathematics
and today's Type Theory, CMU Report CS-88-135, Lecture delivered at the Logic Colloquium
8 \triangleq , Ebbinghaus et al. eds, North Holland, Studies in Logic.
[Longo Moggi 88] G.Longo, E.Moggi: Constructive Natural Deduction and its "ω-Set"
interpretation, CMU report CS-88-131, 1988.
[Luo 88] Z.Luo: ECC, an Extended Calculus of Constructions, Report, LFCS, Department of
Computer Science University of Edinburgh.
[Martini 88] S.Martini: Bounded quantifiers have interval models, ACM Conference on Lisp and
Functional Programming Languages, Snowbird, Utah.
[Meseguer 88] J.Meseguer: Relating Models of Polymorphism, SRI-CSL-88-13, October, SRI
Projects 2316, 4415 and 6 \triangleq 29, SRI International, Comp. sci. Lab.
[Mitchell 84] J.C.Mitchell: Coercion and type inference, Proc. POPL 1984.
[Mitchell 86] J. Mitchell:: A type-inference approach to reduction properties and semantics of
polymorphic expressions ACM Conference on LISP and Functional Programming, Boston (308-
319).
[Mitchell 88] J.Mitchell: Polymorphic Type Inference and Containment, Information and
Computation, Vol.  \triangleq 6, Numbers 2/3, (211-249).
[Mitchell Plotkin 85] J.C.Mitchell, G.D.Plotkin: Abstract types have existential type, Proc. POPL
1985.
[Ohori 8 \triangleq ] A.Ohori: Orderings and types in databases, Proc. of the Workshop on Database
Programming Languages, Roscoff, France, September 198 \triangleq .
[Pitts 8 \triangleq ] A.Pitts: Polymorphism is Set theoretic, constructively, Symposium on Category Theory
and Comp. Sci., SLNCS 283 (Pitts et al. eds.), Edinburgh.
[Reynolds 84] J C.Reynolds: Polymorphism is not set-theoretic, Symposium on Semantics of Data
Types (Kahn, MacQueen, and Plotkin eds.) Lecture Notes in Computer Science 1 \triangleq 3, Springer-
Verlag, 1984, pp. 145-156.


<!-- Page 50 -->

[Rosolini 86] G.Rosolini: Continuity and effectiveness in Topoi, D. Phil. Thesis, Oxford University.
[Scedrov 88] A.Scedrov: A Guide to Polymorphic Types, CIME Lectures Montecatini Terme, June,
(revised version).
[Troelstra  \triangleq 3] A.Troelstra: Metamathematical investigation of Intuitionistic Arithmetic and Analysis.
LNM 344, Springer-Verlag, Berlin.
[Wand 89] M.Wand: Type inference for record concatenation and multiple inheritance, Proc. of
the Fourth Annual Symposium on Logic in Computer Science, 1989.
